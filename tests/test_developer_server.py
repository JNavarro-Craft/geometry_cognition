"""Unit tests for developer_server: snapshot persistence, diff, assert_change.

These tests do NOT require Rhino or the bridge: the bridge client is
monkeypatched with fake payloads representing two model states.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gc_mcp.developer_server import storage, tools
from gc_mcp.developer_server.tools import (
    assert_change,
    diff_object,
    diff_snapshots,
    inspect_object,
    list_snapshots,
    take_snapshot,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _bridge_object(
    guid: str,
    *,
    layer: str = "Default",
    name: str = "",
    raw_type: str = "Brep",
    user_text: dict[str, str] | None = None,
    group_ids: list[str] | None = None,
    group_names: list[str] | None = None,
    bbox_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    bbox_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> dict[str, Any]:
    """Build an object shaped like ``_normalize_bridge_objects`` output."""
    return {
        "object_id": guid,
        "source_system": "rhino_bridge",
        "source_ref": guid,
        "object_kind": "geometric_object",
        "raw_type": raw_type,
        "layer": layer,
        "name": name,
        "group_ids": list(group_ids or []),
        "group_names": list(group_names or []),
        "block_context": {"is_block_instance": False, "block_name": None, "instance_definition_id": None},
        "user_text": dict(user_text or {}),
        "material": None,
        "transform": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "geometry_ref": f"rhino-bridge://{guid}",
        "raw_geometry_summary": {
            "source": "rhino_bridge",
            "bbox": {"min": list(bbox_min), "max": list(bbox_max)},
            "bbox_center": [
                (bbox_min[0] + bbox_max[0]) / 2.0,
                (bbox_min[1] + bbox_max[1]) / 2.0,
                (bbox_min[2] + bbox_max[2]) / 2.0,
            ],
        },
        "extraction_warnings": [],
    }


def _state_before() -> list[dict[str, Any]]:
    return [
        _bridge_object(
            "guid-A",
            layer="L_old",
            name="A",
            user_text={"role": "tread"},
            group_names=["grp1"],
        ),
        _bridge_object(
            "guid-B",
            layer="L1",
            name="B",
            user_text={"key1": "v1"},
            bbox_min=(0, 0, 0),
            bbox_max=(2, 2, 2),
        ),
        _bridge_object(
            "guid-C",
            layer="L1",
            name="C",
            user_text={"key1": "v1", "key2": "v2"},
        ),
    ]


def _state_after() -> list[dict[str, Any]]:
    return [
        # A: deleted (not present)
        # B: modified (layer + bbox)
        _bridge_object(
            "guid-B",
            layer="L1_renamed",
            name="B",
            user_text={"key1": "v1"},
            bbox_min=(0, 0, 0),
            bbox_max=(5, 2, 2),
        ),
        # C: modified (user_text changed_value + added key, group added)
        _bridge_object(
            "guid-C",
            layer="L1",
            name="C",
            user_text={"key1": "vCHANGED", "key2": "v2", "key3": "v3"},
            group_names=["new_group"],
        ),
        # D: created
        _bridge_object(
            "guid-D",
            layer="Stairs",
            name="D",
            raw_type="Mesh",
            user_text={"role": "tread"},
        ),
    ]


def _install_fake_bridge(monkeypatch, state: list[dict[str, Any]]) -> None:
    """Patch the bridge client so take_snapshot returns the given state."""
    def fake_fetch(bridge_url, timeout, *, query_page_limit=200, extract_batch_size=80, filters=None):
        return {"source": "rhino_bridge", "object_count": len(state), "objects": state}

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", fake_fetch)
    monkeypatch.setattr(tools, "extract_objects_bridge", lambda u, t: {"objects": state})
    monkeypatch.setattr(tools, "_bridge_json_request", lambda *a, **k: {"summarize_model_stub": True})
    monkeypatch.setattr(tools, "live_scene_summary_bridge", lambda u, t, sample_limit=20: {"object_count": len(state)})


@pytest.fixture
def isolated_outputs(monkeypatch, tmp_path):
    monkeypatch.setenv("GC_OUTPUTS_DIR", str(tmp_path))
    monkeypatch.setenv("GC_BRIDGE_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("GC_BRIDGE_TIMEOUT_SECONDS", "1")
    return tmp_path


# ---------------------------------------------------------------------------
# storage / slugify
# ---------------------------------------------------------------------------


def test_slugify_label_basic():
    assert storage.slugify_label("antes") == "antes"
    assert storage.slugify_label("Antes Espacio") == "antes_espacio"
    assert storage.slugify_label("  before-1  ") == "before-1"
    assert storage.slugify_label("$$$") == ""
    assert storage.slugify_label("") == ""


def test_take_snapshot_persists_overwrite(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    out1 = take_snapshot("antes")
    assert out1["status"] == "ok"
    assert out1["label"] == "antes"
    assert out1["summary"]["object_count"] == 3
    assert Path(out1["path"]).exists()

    # Same label -> overwrite: the previous file is deleted before the new one
    # is written. (If the two writes occur within the same UTC second the new
    # filename collides with the old one; either way exactly one snapshot per
    # label remains on disk.)
    out2 = take_snapshot("antes")
    assert out2["status"] == "ok"
    assert out2["replaced_previous"] == [out1["path"]]
    assert Path(out2["path"]).exists()
    if out1["path"] != out2["path"]:
        assert Path(out1["path"]).exists() is False

    listing = list_snapshots()
    labels = [s["label"] for s in listing["snapshots"]]
    assert labels.count("antes") == 1


def test_take_snapshot_invalid_label(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    out = take_snapshot("$$$")
    assert out["error"] == "invalid_label"


def test_take_snapshot_live_unavailable(monkeypatch, isolated_outputs):
    def boom(*a, **k):
        raise RuntimeError("bridge_connection_error:Connection refused")

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", boom)
    monkeypatch.setattr(tools, "extract_objects_bridge", boom)
    out = take_snapshot("x")
    assert out["error"] == "live_mode_unavailable"
    assert out["mode"] == "bridge_live"


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_diff_detects_create_delete_modify(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff = diff_snapshots("antes", "despues")
    assert diff["summary"]["created_count"] == 1
    assert diff["summary"]["deleted_count"] == 1
    assert diff["summary"]["modified_count"] == 2
    assert diff["summary"]["unchanged_count"] == 0

    created_ids = [r["object_id"] for r in diff["created"]]
    deleted_ids = [r["object_id"] for r in diff["deleted"]]
    modified_ids = [r["object_id"] for r in diff["modified"]]
    assert created_ids == ["guid-D"]
    assert deleted_ids == ["guid-A"]
    assert sorted(modified_ids) == ["guid-B", "guid-C"]


def test_diff_modify_detail_layer_and_bbox(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff = diff_snapshots("antes", "despues")
    b_row = next(r for r in diff["modified"] if r["object_id"] == "guid-B")
    assert b_row["changes"]["layer"] == {"from": "L1", "to": "L1_renamed"}
    assert b_row["changes"]["bbox"]["changed"] is True
    assert b_row["changes"]["bbox"]["delta_center"] == [1.5, 0.0, 0.0]


def test_diff_modify_detail_user_text_and_groups(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff = diff_snapshots("antes", "despues")
    c_row = next(r for r in diff["modified"] if r["object_id"] == "guid-C")
    ut = c_row["changes"]["user_text"]
    assert ut["added"] == ["key3"]
    assert ut["removed"] == []
    assert {"key": "key1", "from": "v1", "to": "vCHANGED"} in ut["changed"]
    assert c_row["changes"]["group_names"]["added"] == ["new_group"]


def test_diff_unchanged_when_states_match(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    take_snapshot("b")
    diff = diff_snapshots("a", "b")
    assert diff["summary"]["created_count"] == 0
    assert diff["summary"]["deleted_count"] == 0
    assert diff["summary"]["modified_count"] == 0
    assert diff["summary"]["unchanged_count"] == 3


def test_diff_bbox_tolerance(monkeypatch, isolated_outputs):
    state_a = [_bridge_object("g", bbox_min=(0, 0, 0), bbox_max=(1.0, 1.0, 1.0))]
    state_b = [_bridge_object("g", bbox_min=(0, 0, 0), bbox_max=(1.0 + 1e-9, 1.0, 1.0))]

    _install_fake_bridge(monkeypatch, state_a)
    take_snapshot("a")
    _install_fake_bridge(monkeypatch, state_b)
    take_snapshot("b")

    # Default tolerance (1e-6) -> unchanged
    diff_default = diff_snapshots("a", "b")
    assert diff_default["summary"]["modified_count"] == 0

    # Strict tolerance -> modified
    diff_strict = diff_snapshots("a", "b", bbox_tolerance=1e-12)
    assert diff_strict["summary"]["modified_count"] == 1


def test_diff_snapshot_not_found(isolated_outputs):
    out = diff_snapshots("missing_a", "missing_b")
    assert out["error"] == "snapshot_not_found"


# ---------------------------------------------------------------------------
# assert_change
# ---------------------------------------------------------------------------


def test_assert_change_created_with_filter(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    out = assert_change(
        "antes",
        "despues",
        {
            "created": {
                "min": 1,
                "in_layer": "Stairs",
                "with_user_text": {"role": "tread"},
            }
        },
    )
    assert out["passed"] is True
    assert out["results"][0]["rule"] == "created"
    assert out["results"][0]["actual_count"] == 1


def test_assert_change_fails_when_filter_no_match(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    out = assert_change(
        "antes",
        "despues",
        {"created": {"min": 1, "in_layer": "NonExistent"}},
    )
    assert out["passed"] is False
    assert out["results"][0]["actual_count"] == 0


def test_assert_change_modified_with_where(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    out = assert_change(
        "antes",
        "despues",
        {"modified": {"exact": 1, "where": {"in_layer": "L1"}}},
    )
    # guid-C is the only modified object whose layer in state B is "L1"
    # guid-B is also modified but its layer in B is "L1_renamed"
    assert out["passed"] is True
    assert out["results"][0]["actual_count"] == 1


def test_assert_change_deleted_count(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    out = assert_change("antes", "despues", {"deleted": {"exact": 1}})
    assert out["passed"] is True


# ---------------------------------------------------------------------------
# inspect_object
# ---------------------------------------------------------------------------


def test_inspect_object_pass_through(monkeypatch, isolated_outputs):
    monkeypatch.setattr(
        tools,
        "live_object_detail_bridge",
        lambda u, t, oid, detail_level="full", user_text="values": {
            "object_id": oid,
            "detail_level": detail_level,
            "user_text_mode": user_text,
        },
    )
    out = inspect_object("guid-X")
    assert out["status"] == "ok"
    assert out["detail"]["object_id"] == "guid-X"


def test_inspect_object_invalid_guid(isolated_outputs):
    out = inspect_object("")
    assert out["error"] == "invalid_guid"


def test_inspect_object_live_unavailable(monkeypatch, isolated_outputs):
    def boom(*a, **k):
        raise RuntimeError("bridge_connection_error:refused")

    monkeypatch.setattr(tools, "live_object_detail_bridge", boom)
    out = inspect_object("guid-X")
    assert out["error"] == "live_mode_unavailable"


# ---------------------------------------------------------------------------
# list_snapshots
# ---------------------------------------------------------------------------


def test_list_snapshots_reports_object_count(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    listing = list_snapshots()
    assert listing["count"] == 1
    assert listing["snapshots"][0]["object_count"] == 3
    assert listing["snapshots"][0]["label"] == "antes"


def test_snapshot_file_is_valid_json(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    out = take_snapshot("antes")
    data = json.loads(Path(out["path"]).read_text(encoding="utf-8"))
    assert data["schema"] == "developer_snapshot.v2"
    assert data["label"] == "antes"
    assert "objects_by_guid" in data
    assert len(data["objects_by_guid"]) == 3


# ---------------------------------------------------------------------------
# detail=summary and diff_object (eslabon 4: navegabilidad)
# ---------------------------------------------------------------------------


def test_diff_detail_full_matches_default_behaviour(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff_default = diff_snapshots("antes", "despues")
    diff_full = diff_snapshots("antes", "despues", detail="full")
    assert diff_default == diff_full


def test_diff_detail_summary_strips_changes(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    full = diff_snapshots("antes", "despues", detail="full")
    summary = diff_snapshots("antes", "despues", detail="summary")

    assert full["summary"] == summary["summary"]
    assert full["created"] == summary["created"]
    assert full["deleted"] == summary["deleted"]
    assert len(full["modified"]) == len(summary["modified"])
    for row_full, row_summary in zip(full["modified"], summary["modified"]):
        assert row_summary["object_id"] == row_full["object_id"]
        assert row_summary["layer_a"] == row_full["layer_a"]
        assert row_summary["layer_b"] == row_full["layer_b"]
        assert "changes" not in row_summary
        assert row_summary["changed_categories"] == sorted(row_full["changes"].keys())


def test_diff_invalid_detail_returns_error(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    out = diff_snapshots("a", "a", detail="brief")
    assert out["error"] == "invalid_detail"


def test_diff_object_modified_matches_diff_snapshots(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    full = diff_snapshots("antes", "despues", detail="full")
    for row in full["modified"]:
        guid = row["object_id"]
        zoom = diff_object("antes", "despues", guid)
        assert zoom["status"] == "modified"
        assert zoom["object_id"] == guid
        assert zoom["changes"] == row["changes"]


def test_diff_object_unchanged(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    take_snapshot("b")
    guid = "guid-B"
    zoom = diff_object("a", "b", guid)
    assert zoom["status"] == "unchanged"
    assert zoom["object_id"] == guid
    assert "changes" not in zoom


def test_diff_object_created(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff = diff_snapshots("antes", "despues")
    created_guid = diff["created"][0]["object_id"]
    zoom = diff_object("antes", "despues", created_guid)
    assert zoom["status"] == "created"
    assert zoom["object_id"] == created_guid
    assert "full_object_b" in zoom
    assert zoom["full_object_b"]["object_id"] == created_guid


def test_diff_object_deleted(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("antes")
    _install_fake_bridge(monkeypatch, _state_after())
    take_snapshot("despues")

    diff = diff_snapshots("antes", "despues")
    deleted_guid = diff["deleted"][0]["object_id"]
    zoom = diff_object("antes", "despues", deleted_guid)
    assert zoom["status"] == "deleted"
    assert zoom["object_id"] == deleted_guid
    assert "full_object_a" in zoom
    assert zoom["full_object_a"]["object_id"] == deleted_guid


def test_diff_object_not_in_snapshots(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    take_snapshot("b")
    zoom = diff_object("a", "b", "guid-NONEXISTENT")
    assert zoom["status"] == "object_not_in_snapshots"


def test_diff_object_invalid_guid(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    zoom = diff_object("a", "a", "")
    assert zoom["error"] == "invalid_guid"


def test_diff_object_snapshot_not_found(isolated_outputs):
    zoom = diff_object("missing_a", "missing_b", "any-guid")
    assert zoom["error"] == "snapshot_not_found"


# ---------------------------------------------------------------------------
# Fase 0.3: delete_snapshot / prune_snapshots
# ---------------------------------------------------------------------------


def test_delete_snapshot_removes_label(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import delete_snapshot, prune_snapshots_tool_logic

    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("temp")
    assert any(s["label"] == "temp" for s in list_snapshots()["snapshots"])

    res = delete_snapshot("temp")
    assert res["status"] == "ok"
    assert res["deleted_count"] == 1
    assert not any(s["label"] == "temp" for s in list_snapshots()["snapshots"])


def test_delete_snapshot_not_found(isolated_outputs):
    from gc_mcp.developer_server.tools import delete_snapshot

    res = delete_snapshot("does_not_exist")
    assert res["status"] == "not_found"
    assert res["deleted_count"] == 0


def test_delete_snapshot_invalid_label(isolated_outputs):
    from gc_mcp.developer_server.tools import delete_snapshot

    res = delete_snapshot("!!!")
    assert res["error"] == "invalid_label"


def test_prune_snapshots_keeps_latest_per_label(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import prune_snapshots_tool_logic

    # Two distinct labels; take_snapshot overwrites same-label, so create two labels.
    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("keep_me")
    take_snapshot("prune_me")
    assert len(list_snapshots()["snapshots"]) == 2

    # keep_latest_n=1 keeps the newest of EACH label -> nothing deleted here
    res = prune_snapshots_tool_logic(keep_latest_n=1)
    assert res["status"] == "ok"
    assert res["deleted_count"] == 0
    assert res["kept_count"] == 2


def test_prune_snapshots_zero_deletes_all(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import prune_snapshots_tool_logic

    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("a")
    take_snapshot("b")
    res = prune_snapshots_tool_logic(keep_latest_n=0)
    assert res["deleted_count"] == 2
    assert list_snapshots()["count"] == 0


def test_prune_snapshots_invalid_arg(isolated_outputs):
    from gc_mcp.developer_server.tools import prune_snapshots_tool_logic

    res = prune_snapshots_tool_logic(keep_latest_n=-1)
    assert res["error"] == "invalid_keep_latest_n"


# ---------------------------------------------------------------------------
# Fase 0.4: extra fields projected into the snapshot + diffed
# ---------------------------------------------------------------------------


def _read_only_snapshot(label: str) -> dict[str, Any]:
    path = storage.find_latest_by_label(storage.slugify_label(label))
    assert path is not None
    return storage.read_snapshot(path)


def test_snapshot_projects_extra_fields(monkeypatch, isolated_outputs):
    state = [
        _bridge_object("guid-X", layer="L1", name="X"),
    ]
    # Enrich with block + material + kind. NOTE: the bridge delivers block data
    # under ``block_info`` (with instance_definition_index); _normalize_bridge_objects
    # rebuilds block_context from it and ignores a pre-formed block_context.
    state[0]["object_kind"] = "instance_reference"
    state[0]["material"] = "Steel"
    state[0]["block_info"] = {
        "is_block_instance": True,
        "block_name": "ModuleA",
        "instance_definition_index": "idef-1",
    }
    _install_fake_bridge(monkeypatch, state)
    take_snapshot("rich")

    snap = _read_only_snapshot("rich")
    obj = snap["objects_by_guid"]["guid-X"]
    assert obj["object_kind"] == "instance_reference"
    assert obj["material"] == "Steel"
    assert obj["block_context"]["is_block_instance"] is True
    assert obj["block_context"]["block_name"] == "ModuleA"
    assert obj["block_context"]["instance_definition_id"] == "idef-1"
    assert isinstance(obj["transform"], list) and len(obj["transform"]) == 16


def test_diff_detects_block_and_material_changes(monkeypatch, isolated_outputs):
    before = [_bridge_object("guid-X", layer="L1", name="X")]
    before[0]["material"] = "Steel"
    before[0]["block_info"] = {"is_block_instance": True, "block_name": "ModuleA", "instance_definition_index": "idef-1"}
    _install_fake_bridge(monkeypatch, before)
    take_snapshot("b0")

    after = [_bridge_object("guid-X", layer="L1", name="X")]
    after[0]["material"] = "Aluminum"
    after[0]["block_info"] = {"is_block_instance": True, "block_name": "ModuleB", "instance_definition_index": "idef-2"}
    _install_fake_bridge(monkeypatch, after)
    take_snapshot("b1")

    zoom = diff_object("b0", "b1", "guid-X")
    assert zoom["status"] == "modified"
    changes = zoom["changes"]
    assert changes["material"] == {"from": "Steel", "to": "Aluminum"}
    assert changes["block_context"]["block_name"] == {"from": "ModuleA", "to": "ModuleB"}
    assert changes["block_context"]["instance_definition_id"] == {"from": "idef-1", "to": "idef-2"}


# ---------------------------------------------------------------------------
# Fase 0.1/0.2: honest filter report
# ---------------------------------------------------------------------------


def test_filter_report_ok_when_no_filter(monkeypatch, isolated_outputs):
    _install_fake_bridge(monkeypatch, _state_before())
    res = take_snapshot("nofilter")
    assert res["status"] == "ok"
    assert res["filter_report"]["filter_requested"] is False
    assert res["filter_report"]["filter_applied"] is False


def test_filter_report_valid_empty(monkeypatch, isolated_outputs):
    # live strategy succeeds (no fallback warning) but returns 0 objects for the filter
    def fake_fetch_empty(bridge_url, timeout, *, query_page_limit=200, extract_batch_size=80, filters=None):
        return {"source": "rhino_bridge", "object_count": 0, "objects": []}

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", fake_fetch_empty)
    monkeypatch.setattr(tools, "extract_objects_bridge", lambda u, t: {"objects": []})
    monkeypatch.setattr(tools, "_bridge_json_request", lambda *a, **k: {})
    monkeypatch.setattr(tools, "live_scene_summary_bridge", lambda u, t, sample_limit=20: {"object_count": 0})

    res = take_snapshot("emptyfilter", layers=["NonexistentLayer"])
    assert res["status"] == "filter_valid_empty"
    assert res["filter_report"]["filter_applied"] is True
    assert res["filter_report"]["matched_count"] == 0


def test_filter_report_not_applied_on_fallback(monkeypatch, isolated_outputs):
    # live strategy FAILS -> fallback to extract_scene which ignores the filter
    state = _state_before()

    def fake_fetch_fail(bridge_url, timeout, *, query_page_limit=200, extract_batch_size=80, filters=None):
        raise RuntimeError("bridge_live_down")

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", fake_fetch_fail)
    monkeypatch.setattr(tools, "extract_objects_bridge", lambda u, t: {"objects": state})
    monkeypatch.setattr(tools, "_bridge_json_request", lambda *a, **k: {})
    monkeypatch.setattr(tools, "live_scene_summary_bridge", lambda u, t, sample_limit=20: {"object_count": len(state)})

    res = take_snapshot("fallbackfilter", layers=["L1"])
    assert res["status"] == "filter_not_applied"
    assert res["filter_report"]["filter_applied"] is False
    assert "note" in res["filter_report"]


# ---------------------------------------------------------------------------
# Fase 1.1: describe_model (discovery)
# ---------------------------------------------------------------------------


def test_describe_model_catalogues_real_values(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import describe_model

    state = [
        _bridge_object("g1", layer="A::B", raw_type="Brep", user_text={"CF.PartId": "P1"}),
        _bridge_object("g2", layer="A::B", raw_type="Mesh", user_text={"CF.PartId": "P2", "Material": "Steel"}),
        _bridge_object("g3", layer="Other", raw_type="Brep"),
    ]
    state[2]["block_info"] = {"is_block_instance": True, "block_name": "ModuleA", "instance_definition_index": "idef-1"}
    _install_fake_bridge(monkeypatch, state)

    cat = describe_model()
    assert cat["object_count"] == 3
    # layers sorted by count desc: A::B (2) before Other (1)
    assert cat["layers"][0] == {"name": "A::B", "object_count": 2}
    types = {t["raw_type"]: t["object_count"] for t in cat["types"]}
    assert types == {"Brep": 2, "Mesh": 1}
    ut = {k["key"]: k for k in cat["user_text_keys"]}
    assert ut["CF.PartId"]["occurrence_count"] == 2
    assert ut["CF.PartId"]["distinct_values_count"] == 2
    assert ut["Material"]["example_value"] == "Steel"
    assert cat["block_instance_count"] == 1
    assert cat["block_definitions"][0]["block_name"] == "ModuleA"
    assert cat["block_definitions"][0]["instance_count"] == 1


def test_describe_model_live_unavailable(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import describe_model

    def boom(*a, **k):
        raise RuntimeError("bridge down")

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", boom)
    monkeypatch.setattr(tools, "extract_objects_bridge", boom)
    out = describe_model()
    assert out["error"] == "live_mode_unavailable"


# ---------------------------------------------------------------------------
# Fase 1.2: query_objects (live + snapshot)
# ---------------------------------------------------------------------------


def test_query_objects_live_filters(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import query_objects

    state = [
        _bridge_object("g1", layer="L1", raw_type="Brep", name="alpha", user_text={"k": "v1"}),
        _bridge_object("g2", layer="L2", raw_type="Brep", name="beta", user_text={"k": "v2"}),
        _bridge_object("g3", layer="L1", raw_type="Mesh", name="gamma"),
    ]
    _install_fake_bridge(monkeypatch, state)

    r = query_objects(filters={"layers": ["L1"]})
    assert r["matched_count"] == 2
    assert {o["object_id"] for o in r["objects"]} == {"g1", "g3"}

    r2 = query_objects(filters={"layers": ["L1"], "types": ["Brep"]})
    assert r2["matched_count"] == 1 and r2["objects"][0]["object_id"] == "g1"

    r3 = query_objects(filters={"user_text": {"k": "v2"}})
    assert r3["matched_count"] == 1 and r3["objects"][0]["object_id"] == "g2"

    r4 = query_objects(filters={"name_contains": "AMM"})  # case-insensitive 'gamma'
    assert r4["matched_count"] == 1 and r4["objects"][0]["object_id"] == "g3"


def test_query_objects_unknown_filter_value_is_empty(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import query_objects

    _install_fake_bridge(monkeypatch, _state_before())
    r = query_objects(filters={"layers": ["NoSuchLayer"]})
    assert r["matched_count"] == 0


def test_query_objects_over_snapshot(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import query_objects

    _install_fake_bridge(monkeypatch, _state_before())
    take_snapshot("past")
    # Now the live model changes, but we query the PAST snapshot.
    _install_fake_bridge(monkeypatch, _state_after())

    r = query_objects(filters={"layers": ["L1"]}, source="past")
    assert r["source"] == "past"
    # _state_before has guid-B and guid-C in L1
    assert r["matched_count"] == 2
    assert {o["object_id"] for o in r["objects"]} == {"guid-B", "guid-C"}


def test_query_objects_snapshot_not_found(isolated_outputs):
    from gc_mcp.developer_server.tools import query_objects

    r = query_objects(filters={}, source="ghost")
    assert r["error"] == "snapshot_not_found"


def test_query_objects_is_block_instance_filter(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import query_objects

    state = [_bridge_object("g1"), _bridge_object("g2")]
    state[1]["block_info"] = {"is_block_instance": True, "block_name": "M", "instance_definition_index": "i1"}
    _install_fake_bridge(monkeypatch, state)

    r = query_objects(filters={"is_block_instance": True})
    assert r["matched_count"] == 1 and r["objects"][0]["object_id"] == "g2"


# ---------------------------------------------------------------------------
# Filter shape: keys must match the bridge LiveQueryFilters contract
# ---------------------------------------------------------------------------


def test_build_capture_filter_uses_bridge_contract_keys():
    from gc_mcp.developer_server.tools import _build_capture_filter

    flt = _build_capture_filter(
        layers=["L1"],
        types=["Brep"],
        name="abc",
        user_text_key="K",
        bbox={"min": [0, 0, 0], "max": [1, 1, 1]},
    )
    # Bridge contract: name_contains / bbox_intersects (NOT name / bbox).
    assert flt["name_contains"] == "abc"
    assert "name" not in flt
    assert "bbox_intersects" in flt
    assert "bbox" not in flt
    assert flt["layers"] == ["L1"]
    assert flt["types"] == ["Brep"]
    assert flt["user_text_key"] == "K"


def test_build_capture_filter_none_when_empty():
    from gc_mcp.developer_server.tools import _build_capture_filter

    assert _build_capture_filter(None, None, None, None, None) is None


def test_take_snapshot_name_filter_persists_name_contains(monkeypatch, isolated_outputs):
    captured: dict[str, Any] = {}

    def fake_fetch(bridge_url, timeout, *, query_page_limit=200, extract_batch_size=80, filters=None):
        captured["filters"] = filters
        return {"source": "rhino_bridge", "object_count": 0, "objects": []}

    monkeypatch.setattr(tools, "fetch_scene_via_live_query_and_extract_objects", fake_fetch)
    monkeypatch.setattr(tools, "extract_objects_bridge", lambda u, t: {"objects": []})
    monkeypatch.setattr(tools, "_bridge_json_request", lambda *a, **k: {})
    monkeypatch.setattr(tools, "live_scene_summary_bridge", lambda u, t, sample_limit=20: {"object_count": 0})

    take_snapshot("byname", name="Foo")
    # The filter handed to the bridge must use the contract key, not "name".
    assert captured["filters"] == {"name_contains": "Foo"}


# ---------------------------------------------------------------------------
# Fase 2: block definitions + annotation text
# ---------------------------------------------------------------------------


def test_list_block_definitions_passthrough(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import list_block_definitions

    payload = {
        "source": "rhino_bridge",
        "definition_count": 1,
        "definitions": [
            {"definition_name": "ModuleA", "object_count": 5, "instance_count": 40, "bbox": {}},
        ],
    }
    monkeypatch.setattr(tools, "live_list_definitions_bridge", lambda u, t: payload)
    out = list_block_definitions()
    assert out["definition_count"] == 1
    assert out["definitions"][0]["definition_name"] == "ModuleA"
    assert out["definitions"][0]["instance_count"] == 40


def test_list_block_definitions_live_unavailable(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import list_block_definitions

    def boom(u, t):
        raise RuntimeError("down")

    monkeypatch.setattr(tools, "live_list_definitions_bridge", boom)
    assert list_block_definitions()["error"] == "live_mode_unavailable"


def test_expand_block_passthrough(monkeypatch, isolated_outputs):
    from gc_mcp.developer_server.tools import expand_block

    captured = {}

    def fake(u, t, name):
        captured["name"] = name
        return {"definition_name": name, "object_count": 2, "transform_applied": False, "objects": [{"object_id": "c1"}, {"object_id": "c2"}]}

    monkeypatch.setattr(tools, "live_definition_objects_bridge", fake)
    out = expand_block("ModuleA")
    assert captured["name"] == "ModuleA"
    assert out["object_count"] == 2
    assert out["transform_applied"] is False


def test_expand_block_empty_name(isolated_outputs):
    from gc_mcp.developer_server.tools import expand_block

    assert expand_block("  ")["error"] == "invalid_definition_name"


def test_snapshot_projects_and_diffs_annotation_text(monkeypatch, isolated_outputs):
    before = [_bridge_object("g-anno", layer="Notes", raw_type="Annotation", name="")]
    before[0]["annotation_text"] = {"kind": "TextEntity", "plain_text": "PANEL-001"}
    _install_fake_bridge(monkeypatch, before)
    take_snapshot("t0")

    snap = _read_only_snapshot("t0")
    assert snap["objects_by_guid"]["g-anno"]["annotation_text"] == "PANEL-001"

    after = [_bridge_object("g-anno", layer="Notes", raw_type="Annotation", name="")]
    after[0]["annotation_text"] = {"kind": "TextEntity", "plain_text": "PANEL-002"}
    _install_fake_bridge(monkeypatch, after)
    take_snapshot("t1")

    zoom = diff_object("t0", "t1", "g-anno")
    assert zoom["status"] == "modified"
    assert zoom["changes"]["annotation_text"] == {"from": "PANEL-001", "to": "PANEL-002"}
