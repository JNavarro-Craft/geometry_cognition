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
    get_joints_bridge,
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
