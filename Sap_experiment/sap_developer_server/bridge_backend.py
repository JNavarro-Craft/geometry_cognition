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


def set_model_locked_bridge(
    base_url: str, timeout_seconds: float, locked: bool, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"locked": locked, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/model/locked", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def open_model_bridge(
    base_url: str, timeout_seconds: float, path: str, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"path": path, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    # OpenFile can take a moment on larger models.
    return _bridge_json_request(
        base_url, "/v1/model/open", max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def new_blank_model_bridge(
    base_url: str, timeout_seconds: float, units: str, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"units": units, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/model/new_blank", max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def reset_workspace_bridge(
    base_url: str, timeout_seconds: float, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/workspace/reset", max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def save_workspace_as_bridge(
    base_url: str, timeout_seconds: float, path: str, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps({"path": path, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/workspace/save_as", max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


# --- Geometry: joints (Fase 1h.2) --------------------------------------------

def create_joint_bridge(
    base_url: str, timeout_seconds: float, x: float, y: float, z: float,
    name: str | None, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"x": x, "y": y, "z": z, "name": name,
                       "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/joints", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def create_joints_bridge(
    base_url: str, timeout_seconds: float, joints: list[dict], dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"joints": joints, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/joints/batch", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def delete_joint_bridge(
    base_url: str, timeout_seconds: float, name: str, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(name)}", timeout_seconds,
        method="DELETE", body=body, content_type="application/json",
    )


def modify_joint_bridge(
    base_url: str, timeout_seconds: float, name: str, x: float, y: float, z: float,
    dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"x": x, "y": y, "z": z, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(name)}", timeout_seconds,
        method="PATCH", body=body, content_type="application/json",
    )


# --- Geometry: frames (Fase 1h.2) --------------------------------------------

def create_frame_bridge(
    base_url: str, timeout_seconds: float, joint_i_name: str, joint_j_name: str,
    section: str | None, name: str | None, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"joint_i_name": joint_i_name, "joint_j_name": joint_j_name,
                       "section": section, "name": name,
                       "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/frames", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def create_frames_bridge(
    base_url: str, timeout_seconds: float, frames: list[dict], dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"frames": frames, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/frames/batch", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def delete_frame_bridge(
    base_url: str, timeout_seconds: float, name: str, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/frames/{quote(name)}", timeout_seconds,
        method="DELETE", body=body, content_type="application/json",
    )


def modify_frame_bridge(
    base_url: str, timeout_seconds: float, name: str, joint_i_name: str | None,
    joint_j_name: str | None, section: str | None, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"joint_i_name": joint_i_name, "joint_j_name": joint_j_name,
                       "section": section, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/frames/{quote(name)}", timeout_seconds,
        method="PATCH", body=body, content_type="application/json",
    )


def set_frame_releases_bridge(
    base_url: str, timeout_seconds: float, name: str, releases_i: dict, releases_j: dict,
    dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"releases_i": releases_i, "releases_j": releases_j,
                       "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/frames/{quote(name)}/releases", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


# --- Load patterns (Fase 1h.4) -----------------------------------------------

def create_load_pattern_bridge(
    base_url: str, timeout_seconds: float, name: str, pattern_type: str,
    self_weight_multiplier: float, add_load_case: bool, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"name": name, "pattern_type": pattern_type,
                       "self_weight_multiplier": self_weight_multiplier,
                       "add_load_case": add_load_case,
                       "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/load_patterns", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


# --- Joint loads (Fase 1h.4) -------------------------------------------------

def assign_joint_load_bridge(
    base_url: str, timeout_seconds: float, joint_name: str, pattern_name: str,
    forces: dict | None, moments: dict | None, coord_sys: str, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"pattern_name": pattern_name, "forces": forces or {},
                       "moments": moments or {}, "coord_sys": coord_sys,
                       "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(joint_name)}/loads", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def assign_joint_loads_batch_bridge(
    base_url: str, timeout_seconds: float, items: list[dict], dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"items": items, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/joints/loads/batch", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def clear_joint_loads_bridge(
    base_url: str, timeout_seconds: float, joint_name: str, pattern_name: str | None,
    dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"pattern_name": pattern_name, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(joint_name)}/loads", timeout_seconds,
        method="DELETE", body=body, content_type="application/json",
    )


def get_joint_loads_bridge(
    base_url: str, timeout_seconds: float, joint_name: str,
) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(joint_name)}/loads", timeout_seconds, method="GET",
    )


# --- Joint restraints (Fase 1h.3) --------------------------------------------

def get_joint_restraints_bridge(
    base_url: str, timeout_seconds: float, name: str,
) -> dict[str, Any]:
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(name)}/restraints", timeout_seconds, method="GET",
    )


def set_joint_restraints_bridge(
    base_url: str, timeout_seconds: float, name: str, restraints: dict, dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"restraints": restraints, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, f"/v1/joints/{quote(name)}/restraints", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def set_joint_restraints_batch_bridge(
    base_url: str, timeout_seconds: float, items: list[dict], dry_run: bool, confirm: bool,
) -> dict[str, Any]:
    body = json.dumps({"items": items, "dry_run": dry_run, "confirm": confirm}).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/joints/restraints/batch", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def create_material_bridge(
    base_url: str, timeout_seconds: float, name: str, material_type: str, dry_run: bool
) -> dict[str, Any]:
    body = json.dumps(
        {"name": name, "material_type": material_type, "dry_run": dry_run}
    ).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/materials", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def set_material_properties_isotropic_bridge(
    base_url: str, timeout_seconds: float, name: str, E: float, poisson_ratio: float,
    thermal_coef: float, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    path = f"/v1/materials/{quote(name, safe='')}/properties/isotropic"
    body = json.dumps({
        "E": E, "poisson_ratio": poisson_ratio, "thermal_coef": thermal_coef,
        "dry_run": dry_run, "confirm": confirm,
    }).encode("utf-8")
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="POST", body=body, content_type="application/json",
    )


def create_rectangular_section_bridge(
    base_url: str, timeout_seconds: float, name: str, material: str, depth: float,
    width: float, color, notes: str, dry_run: bool
) -> dict[str, Any]:
    body = json.dumps({
        "name": name, "material": material, "depth": depth, "width": width,
        "color": color, "notes": notes, "dry_run": dry_run,
    }).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/sections", timeout_seconds,
        method="POST", body=body, content_type="application/json",
    )


def modify_rectangular_section_bridge(
    base_url: str, timeout_seconds: float, name: str, material, depth, width, color, notes,
    dry_run: bool, confirm: bool
) -> dict[str, Any]:
    path = f"/v1/sections/{quote(name, safe='')}"
    body = json.dumps({
        "material": material, "depth": depth, "width": width, "color": color,
        "notes": notes, "dry_run": dry_run, "confirm": confirm,
    }).encode("utf-8")
    return _bridge_json_request(
        base_url, path, timeout_seconds, method="PATCH", body=body, content_type="application/json",
    )


def assign_section_to_frames_bridge(
    base_url: str, timeout_seconds: float, section_name: str, frame_names: list,
    dry_run: bool, confirm: bool
) -> dict[str, Any]:
    path = f"/v1/sections/{quote(section_name, safe='')}/assign-to-frames"
    body = json.dumps(
        {"frame_names": frame_names, "dry_run": dry_run, "confirm": confirm}
    ).encode("utf-8")
    # Batch over many frames can take a moment; allow more than the read timeout.
    return _bridge_json_request(
        base_url, path, max(timeout_seconds, 120.0),
        method="POST", body=body, content_type="application/json",
    )


def assign_sections_to_frames_bridge(
    base_url: str, timeout_seconds: float, assignments: list, dry_run: bool, confirm: bool
) -> dict[str, Any]:
    body = json.dumps(
        {"assignments": assignments, "dry_run": dry_run, "confirm": confirm}
    ).encode("utf-8")
    return _bridge_json_request(
        base_url, "/v1/sections/assign-batch", max(timeout_seconds, 120.0),
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
