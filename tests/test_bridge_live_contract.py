from __future__ import annotations

from gc_mcp.rhino_bridge_client import backend_adapter, bridge_backend
from gc_mcp.rhino_bridge_client.tools import extract_objects


def test_bridge_health_calls_health_endpoint(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_bridge_json_request(base_url, path, timeout_seconds, **kwargs):
        calls.append((base_url, path))
        return {"status": "ok"}

    monkeypatch.setattr(bridge_backend, "_bridge_json_request", _fake_bridge_json_request)
    out = bridge_backend.bridge_health("http://127.0.0.1:8765", 3.0)

    assert out["status"] == "ok"
    assert calls == [("http://127.0.0.1:8765", "/health")]


def test_live_scene_summary_calls_summary_endpoint(monkeypatch):
    calls: list[str] = []

    def _fake_bridge_json_request(base_url, path, timeout_seconds, **kwargs):
        calls.append(path)
        return {"object_count": 5}

    monkeypatch.setattr(bridge_backend, "_bridge_json_request", _fake_bridge_json_request)
    out = bridge_backend.live_scene_summary_bridge("http://bridge", 5.0, sample_limit=999)

    assert out["object_count"] == 5
    assert calls == ["/v1/live/scene/summary?sample_limit=100"]


def test_live_query_collect_ids_and_detail_paths(monkeypatch):
    observed: list[str] = []

    def _fake_bridge_json_request(base_url, path, timeout_seconds, **kwargs):
        observed.append(path)
        if path == "/v1/live/objects/query":
            payload = kwargs["body"].decode("utf-8")
            if '"cursor": 0' in payload:
                return {"objects": [{"object_id": "a"}, {"object_id": "b"}], "next_cursor": 2}
            return {"objects": [{"object_id": "c"}]}
        if path.startswith("/v1/live/objects/"):
            return {"object_id": "a"}
        raise AssertionError(path)

    monkeypatch.setattr(bridge_backend, "_bridge_json_request", _fake_bridge_json_request)

    ids = bridge_backend.collect_object_ids_via_live_query("http://bridge", 5.0, page_limit=2)
    detail = bridge_backend.live_object_detail_bridge(
        "http://bridge",
        5.0,
        "a",
        detail_level="basic",
        user_text="keys",
    )

    assert ids == ["a", "b", "c"]
    assert detail["object_id"] == "a"
    assert "/v1/live/objects/query" in observed
    assert "/v1/live/objects/a?detail_level=basic&user_text=keys" in observed


def test_fetch_scene_via_live_query_uses_batches(monkeypatch):
    monkeypatch.setattr(
        bridge_backend,
        "collect_object_ids_via_live_query",
        lambda base_url, timeout_seconds, page_limit=200, filters=None: ["o1", "o2", "o3"],
    )
    requested_chunks: list[list[str]] = []

    def _fake_extract_by_ids(base_url, timeout_seconds, object_ids):
        requested_chunks.append(list(object_ids))
        return {"objects": [{"object_id": oid} for oid in object_ids]}

    monkeypatch.setattr(bridge_backend, "extract_objects_by_ids_bridge", _fake_extract_by_ids)

    out = bridge_backend.fetch_scene_via_live_query_and_extract_objects(
        "http://bridge",
        5.0,
        query_page_limit=50,
        extract_batch_size=2,
    )

    assert out["object_count"] == 3
    assert [obj["object_id"] for obj in out["objects"]] == ["o1", "o2", "o3"]
    assert requested_chunks == [["o1", "o2"], ["o3"]]


def test_backend_adapter_prefers_live_strategy(monkeypatch):
    monkeypatch.setenv("GC_BACKEND_MODE", "bridge")
    monkeypatch.setenv("GC_BRIDGE_FETCH_STRATEGY", "live")
    monkeypatch.setenv("GC_BRIDGE_FALLBACK_LOCAL", "false")
    monkeypatch.setattr(
        backend_adapter,
        "fetch_scene_via_live_query_and_extract_objects",
        lambda bridge_url, timeout, query_page_limit=200, extract_batch_size=80: {
            "objects": [
                {
                    "object_id": "live-1",
                    "source_ref": "live-1",
                    "type": "Brep",
                    "layer": "",
                    "name": "",
                    "group_ids": [],
                    "group_names": [],
                    "user_text": {},
                    "material": None,
                    "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                    "raw_geometry_summary": {"bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}},
                }
            ]
        },
    )
    out = extract_objects({})
    assert out["status"] == "ok"
    assert out["backend_mode"] == "bridge"
    assert out["objects"][0]["object_id"] == "live-1"
    assert "bridge_strategy:live" in out["backend_warnings"]
