from gc_mcp.verification_executor.tools import execute_verification_plan


def _base_relation() -> dict:
    return {
        "relation_id": "rel-001",
        "subject_id": "obj-a",
        "predicate": "touches",
        "object_id": "obj-b",
        "relation_type": "spatial",
        "directionality": "symmetric",
        "confidence": 0.76,
        "tolerance_context": {"linear_tolerance": 0.05, "angular_tolerance": 2.0, "unit_system": "model_unit"},
        "observation_refs": ["obs:touching_candidate:obj-a:obj-b"],
        "limitations": ["bbox_based", "candidate_relation"],
        "derived_from": ["geometry_schema.v2.json"],
        "assertion_level": "candidate",
        "inference_basis": "bbox_gap_within_tolerance",
        "measurement_method": "aabb_gap",
        "verification_status": "unverified",
        "verification_required": ["mesh_distance_check"],
        "confidence_basis": ["aabb gap near tolerance"],
    }


def test_execute_verification_plan_promotes_verified_confirmed(monkeypatch):
    def fake_post(_base_url: str, _payload: dict):
        return {
            "source": "rhino_bridge",
            "results": [
                {
                    "relation_id": "rel-001",
                    "subject_id": "obj-a",
                    "object_id": "obj-b",
                    "check": "mesh_distance_check",
                    "verification_status": "verified",
                    "assertion_level": "confirmed",
                    "method": "mesh_distance",
                    "measurements": {"distance": 0.0, "intersection_count": 0, "contact_area_estimate": None},
                    "confidence": 0.9,
                    "limitations": [],
                    "notes": [],
                }
            ],
        }

    monkeypatch.setattr("gc_mcp.verification_executor.tools._post_verify_relations", fake_post)
    out = execute_verification_plan(
        {
            "verification_plan": [{"relation_id": "rel-001", "recommended_check": "mesh_distance_check"}],
            "relations": [_base_relation()],
            "bridge_base_url": "http://127.0.0.1:8765",
            "max_items": 5,
        }
    )
    assert out["status"] == "ok"
    rel = out["updated_relations"][0]
    assert rel["assertion_level"] == "confirmed"
    assert rel["verification_status"] == "verified"
    assert rel["verification_required"] == []
    assert "candidate_relation" not in rel["limitations"]
    assert rel["verification_result"]["source"] == "rhino_bridge"


def test_execute_verification_plan_marks_contradicted_as_measured(monkeypatch):
    def fake_post(_base_url: str, _payload: dict):
        return {
            "source": "rhino_bridge",
            "results": [
                {
                    "relation_id": "rel-001",
                    "subject_id": "obj-a",
                    "object_id": "obj-b",
                    "check": "mesh_distance_check",
                    "verification_status": "contradicted",
                    "assertion_level": "measured",
                    "method": "mesh_distance",
                    "measurements": {"distance": 1.5, "intersection_count": 0, "contact_area_estimate": None},
                    "confidence": 0.78,
                    "limitations": [],
                    "notes": [],
                }
            ],
        }

    monkeypatch.setattr("gc_mcp.verification_executor.tools._post_verify_relations", fake_post)
    out = execute_verification_plan(
        {
            "verification_plan": [{"relation_id": "rel-001", "recommended_check": "mesh_distance_check"}],
            "relations": [_base_relation()],
        }
    )
    rel = out["updated_relations"][0]
    assert rel["assertion_level"] == "measured"
    assert rel["verification_status"] == "contradicted"
    assert "candidate_relation_contradicted_by_verification" in rel["limitations"]


def test_execute_verification_plan_bridge_failure_returns_error(monkeypatch):
    def fake_post(_base_url: str, _payload: dict):
        raise RuntimeError("bridge verification request failed: connection refused")

    monkeypatch.setattr("gc_mcp.verification_executor.tools._post_verify_relations", fake_post)
    out = execute_verification_plan(
        {
            "verification_plan": [{"relation_id": "rel-001", "recommended_check": "mesh_distance_check"}],
            "relations": [_base_relation()],
        }
    )
    assert out["status"] == "error"
    assert "bridge verification request failed" in out["message"]


def test_execute_verification_plan_output_has_no_constructive_terms(monkeypatch):
    def fake_post(_base_url: str, _payload: dict):
        return {"source": "rhino_bridge", "results": []}

    monkeypatch.setattr("gc_mcp.verification_executor.tools._post_verify_relations", fake_post)
    out = execute_verification_plan(
        {
            "verification_plan": [{"relation_id": "rel-001", "recommended_check": "mesh_distance_check"}],
            "relations": [_base_relation()],
        }
    )
    text = str(out).lower()
    for term in ["beam", "panel", "stud", "track", "diagonal", "connector", "truss", "sip"]:
        assert term not in text
