"""Honest failure modes for the SAP bridge.

Ported in spirit from RhinoSAP/Core/ErrorCodes.cs: an explicit enumeration of how
the bridge can fail, so HTTP responses carry a stable, machine-readable ``code``
alongside a human ``message`` (see ``contracts.ErrorResponse``). Consumers (the MCP
today, Rhino plugins and scripts tomorrow) branch on the code, not on the prose.

These describe TRANSPORT / SESSION failure, never domain judgement.
"""
from __future__ import annotations

# Session / connection
SESSION_NOT_ATTACHED = "session_not_attached"
"""No SAP2000 instance is attached. The bridge is attach-only: open SAP2000 and a
model first, then retry."""

SAP_NOT_RUNNING = "sap_not_running"
"""Attach was attempted but no running SAP2000 instance was found (COM GetObject
failed)."""

SAP_PROCESS_DIED = "sap_process_died"
"""A session existed but the SAP2000 process stopped responding (health probe
failed). The session has been reset; re-attach and retry."""

NO_MODEL_OPEN = "no_model_open"
"""Attached to SAP2000 but no model is open / the model handle is invalid."""

# OAPI call
OAPI_CALL_FAILED = "oapi_call_failed"
"""An OAPI call returned a non-zero status. The numeric status is included in the
message; the bridge does not interpret what it means."""

OAPI_UNEXPECTED_SHAPE = "oapi_unexpected_shape"
"""An OAPI call succeeded but returned data the bridge could not read as expected
(e.g. a null array where a name list was expected). Reported, never silently
patched — this is exactly the silent-bug class geometry_cognition hunts."""

# Bridge internals
PYTHONNET_UNAVAILABLE = "pythonnet_unavailable"
"""pythonnet / the SAP2000v1 assembly could not be loaded. The bridge cannot talk
to SAP without it."""

ASSEMBLY_NOT_FOUND = "assembly_not_found"
"""SAP2000v1.dll was not found at the configured or auto-resolved path."""
