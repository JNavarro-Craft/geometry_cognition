"""HTTP client for the SAP bridge. Transport only — no interpretation.

Mirrors gc_mcp/rhino_bridge_client/bridge_backend.py: a thin urllib wrapper that
surfaces the bridge's structured {error, code, message} body instead of flattening
every non-2xx to a bare status. The MCP tools import these functions.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def bridge_settings() -> tuple[str, float]:
    """Bridge base URL + timeout from env. Defaults to the SAP bridge port 8766."""
    base_url = str(os.environ.get("SAP_BRIDGE_BASE_URL", "http://127.0.0.1:8766"))
    timeout = float(os.environ.get("SAP_BRIDGE_TIMEOUT_SECONDS", "10") or "10")
    return base_url, timeout


def _bridge_json_request(
    base_url: str,
    path: str,
    timeout_seconds: float,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = "application/json",
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    headers: dict[str, str] = {}
    if content_type and body is not None:
        headers["Content-Type"] = content_type
    req = Request(url=url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as exc:
        # The bridge puts an honest {error, code, message} JSON in the body (e.g. a
        # 409 sap_not_running). Surface it instead of flattening to a status code.
        detail = ""
        try:
            raw = exc.read().decode("utf-8") if exc.fp is not None else ""
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("code"):
                    msg = parsed.get("message", "")
                    detail = f":{parsed['code']}" + (f" ({msg})" if msg else "")
        except Exception:
            detail = ""
        raise RuntimeError(f"bridge_http_error:{exc.code}{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"bridge_connection_error:{exc.reason}") from exc

    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("bridge_invalid_json_response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("bridge_invalid_response_shape")
    return payload


def bridge_health(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/health", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_units_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/units", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_model_settings_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/model/settings", timeout_seconds, method="GET", body=None, content_type=None
    )


def set_active_dof_bridge(
    base_url: str, timeout_seconds: float, active_dof: list, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps(
        {"active_dof": active_dof, "dry_run": dry_run, "confirm": confirm}
    ).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/model/settings/active_dof", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def set_present_units_bridge(
    base_url: str, timeout_seconds: float, units: str, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"units": units, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/model/settings/present_units", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def create_savepoint_bridge(
    base_url: str, timeout_seconds: float, name: str, dry_run: bool
) -> dict[str, Any]:
    body = json.dumps({"name": name, "dry_run": dry_run}).encode("utf-8")
    # Save/reopen can take a moment on larger models; allow more than the read timeout.
    return _bridge_json_request(
        base_url, "/v1/savepoints", max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def restore_savepoint_bridge(
    base_url: str, timeout_seconds: float, name: str, confirm: bool, dry_run: bool
) -> dict[str, Any]:
    path = f"/v1/savepoints/{quote(name, safe='')}/restore"
    body = json.dumps({"confirm": confirm, "dry_run": dry_run}).encode("utf-8")
    return _bridge_json_request(
        base_url, path, max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def list_savepoints_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/savepoints", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_joints_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/joints", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_frames_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/frames", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_sections_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/sections", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_materials_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/materials", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_load_patterns_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/load_patterns", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_load_cases_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/load_cases", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_combinations_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/combinations", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_distributed_loads_on_frame_bridge(
    base_url: str, timeout_seconds: float, frame_name: str
) -> dict[str, Any]:
    path = f"/v1/frames/{quote(frame_name, safe='')}/loads/distributed"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def get_point_loads_on_joint_bridge(
    base_url: str, timeout_seconds: float, joint_name: str
) -> dict[str, Any]:
    path = f"/v1/joints/{quote(joint_name, safe='')}/loads/point"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def get_load_case_details_bridge(
    base_url: str, timeout_seconds: float, case_name: str
) -> dict[str, Any]:
    path = f"/v1/load_cases/{quote(case_name, safe='')}/details"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def run_analysis_bridge(
    base_url: str, timeout_seconds: float, cases_to_run: list[str] | None
) -> dict[str, Any]:
    # POST: this mutates computation state. RunAnalysis is blocking, so give it a long
    # timeout (analysis can outlast the default read timeout).
    body = json.dumps({"cases_to_run": cases_to_run}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/analysis/run", max(timeout_seconds, 300.0),
        method="POST", body=body, content_type="application/json",
    )


def get_analysis_status_bridge(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, "/v1/analysis/status", timeout_seconds, method="GET", body=None, content_type=None
    )


def get_joint_displacements_bridge(
    base_url: str, timeout_seconds: float, joint_name: str, case_name: str
) -> dict[str, Any]:
    path = f"/v1/joints/{quote(joint_name, safe='')}/displacements/{quote(case_name, safe='')}"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def get_joint_reactions_bridge(
    base_url: str, timeout_seconds: float, joint_name: str, case_name: str
) -> dict[str, Any]:
    path = f"/v1/joints/{quote(joint_name, safe='')}/reactions/{quote(case_name, safe='')}"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def get_frame_forces_bridge(
    base_url: str, timeout_seconds: float, frame_name: str, case_name: str,
    station: float | None = None,
) -> dict[str, Any]:
    path = f"/v1/frames/{quote(frame_name, safe='')}/forces/{quote(case_name, safe='')}"
    if station is not None:
        path += f"?station={station}"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )


def get_section_properties_bridge(
    base_url: str, timeout_seconds: float, name: str
) -> dict[str, Any]:
    # Section names are model-supplied labels and may contain characters that need
    # escaping in a path segment; quote with an empty safe set.
    path = f"/v1/sections/{quote(name, safe='')}/properties"
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="GET", body=None, content_type=None
    )
