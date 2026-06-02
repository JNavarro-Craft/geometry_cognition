"""MCP tool logic: relay facts from the SAP bridge. No structural interpretation.

Each tool calls the bridge over HTTP and returns its JSON essentially verbatim,
adding only an honest error envelope on transport failure. The agnostic test
(brief, Principle 1) holds: these return joints/frames/sections — facts that exist
in any solver — never is_*/verify_*/check_* judgements.
"""
from __future__ import annotations

from typing import Any

from .bridge_backend import (
    bridge_settings,
    get_frames_bridge,
    get_joints_bridge,
    get_sections_bridge,
)


def _bridge_error(exc: Exception) -> dict[str, Any]:
    """Uniform error envelope for the LLM when the bridge is unreachable or errored.
    The bridge's own {code, message} is embedded in the RuntimeError string."""
    return {
        "error": "bridge_unavailable",
        "message": str(exc),
        "hint": "Is the SAP bridge running on its port and is SAP2000 open with a model?",
    }


def get_joints() -> dict[str, Any]:
    """Every point object in the open SAP model: name, global Cartesian coordinates
    (in the model's present units, echoed under ``units``) and the raw 6-DOF
    restraint flags [U1,U2,U3,R1,R2,R3] (True = restrained).

    Facts only. This does not classify supports as pinned/fixed/roller — that mapping
    is structural domain and belongs to you, the client, not the MCP.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_joints_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001 — relay transport failure honestly
        return _bridge_error(exc)


def get_frames() -> dict[str, Any]:
    """Every frame (line) object in the open SAP model: name, the two end point names
    (``point_i`` / ``point_j`` — they match the names from get_joints, so you join on
    them to get coordinates) and the assigned ``section`` property name.

    Facts only. This does not classify frames as chords/struts/diagonals — that role
    reasoning emerges from connectivity and dimensions in the client, not the MCP.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_frames_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)


def get_sections() -> dict[str, Any]:
    """The frame section property catalogue defined in the open SAP model: each
    section's ``name`` and its SAP ``prop_type`` (e.g. 'Rectangular').

    Facts only. Section names are model-supplied labels relayed verbatim — the MCP
    does not interpret them or resolve their geometric dimensions. To know which
    sections are actually *used*, cross-reference with get_frames (the ``section``
    field there); this tool lists what is *defined*.
    """
    base_url, timeout = bridge_settings()
    try:
        return get_sections_bridge(base_url, timeout)
    except Exception as exc:  # noqa: BLE001
        return _bridge_error(exc)
