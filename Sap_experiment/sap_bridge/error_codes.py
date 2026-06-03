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

# Results preconditions (Fase 1e)
CASE_NOT_RUN = "case_not_run"
"""Results were requested for a load case that exists but has not been analysed (no
results to read). The client should call run_analysis first. Client-fixable."""

UNSUPPORTED_CASE_TYPE = "unsupported_case_type"
"""Results were requested for a case type this phase does not resolve (e.g. Modal,
ResponseSpectrum). The case and its type are valid; the bridge just does not expose
its results yet. Not a transport failure."""

# Write-side (see docs/write_side_design.md). Declared here as the stable vocabulary
# every write primitive branches on; some are not used until later 1g sub-phases.
CONFIRM_REQUIRED = "confirm_required"
"""A destructive write (modify/delete a pre-existing object, delete any object, or
change a global model setting) was attempted without confirm=true."""

PREFIX_REQUIRED = "prefix_required"
"""A create operation was attempted without the bridge's namespace prefix on the new
object's name (default 'AI_'; see BRIDGE_NAMESPACE_PREFIX)."""

NAME_ALREADY_EXISTS = "name_already_exists"
"""A create operation targets a name already taken."""

OBJECT_NOT_FOUND = "object_not_found"
"""A write references an object that does not exist."""

DRY_RUN_VALIDATION_FAILED = "dry_run_validation_failed"
"""A dry-run pre-validation detected a problem that would make the real write fail."""

SAVEPOINT_NOT_FOUND = "savepoint_not_found"
"""A restore or info request references a savepoint that does not exist on disk."""

SAVEPOINT_ALREADY_EXISTS = "savepoint_already_exists"
"""A create_savepoint targets a name whose file already exists. Refused rather than
overwritten, to avoid silently losing a prior savepoint."""

UNKNOWN_UNIT_SYSTEM = "unknown_unit_system"
"""set_present_units was given a unit-system name that is not a member of the SAP eUnits
enum. The message lists the supported names. Client-fixable (fix the name and retry)."""

UNKNOWN_MATERIAL_TYPE = "unknown_material_type"
"""create_material was given a material-type name that is not a member of the SAP
eMatType enum (e.g. 'Wood', which SAP26 does not have). The message lists the supported
names. Client-fixable."""

INVALID_DIMENSIONS = "invalid_dimensions"
"""A create/modify was given a non-positive dimension (depth/width <= 0). Shape
validation by the bridge, not domain judgement. Client-fixable."""

SECTION_TYPE_MISMATCH = "section_type_mismatch"
"""A modify targets a section that exists but is not of the expected shape type (e.g.
modify_rectangular_section on a non-Rectangular section). The message reports the actual
type. Client-fixable."""

NOTHING_TO_MODIFY = "nothing_to_modify"
"""A modify was called with no field to change (all optional kwargs are None)."""

EMPTY_BATCH = "empty_batch"
"""A batch write was called with an empty list of items (no frames / no assignments)."""

FILE_NOT_FOUND = "file_not_found"
"""open_model was given a path that does not exist on disk. Checked by the bridge before
calling OpenFile (SAP would otherwise leave the session pointing at a phantom file)."""

INVALID_PATH = "invalid_path"
"""open_model was given a path that is not absolute or does not end in .sdb."""

UNKNOWN_LOAD_PATTERN_TYPE = "unknown_load_pattern_type"
"""create_load_pattern was given a pattern-type name that is not a member of eLoadPatternType
(case-insensitive). The message lists the supported names. Client-fixable (Fase 1h.4)."""

UNKNOWN_LOAD_DIRECTION = "unknown_load_direction"
"""A frame-load primitive was given a direction string the bridge does not map (not one of
Local1/2/3, X/Y/Z, XProj/YProj/ZProj, Gravity, GravityProj). The message lists the supported
names. Client-fixable (Fase 1h.4, §35)."""

JOINT_HAS_CONNECTED_FRAMES = "joint_has_connected_frames"
"""delete_joint was called on a joint that still has frames connected to it (as i or j end).
SAP only deletes points with no connected objects (§33); the bridge refuses and lists the
connected frames so the client can delete those first. No automatic cascade (decisión #5)."""

EMPTY_MODEL = "empty_model"
"""save_workspace_as was asked to materialize a model with no joints and no frames.
Verified empirically (brechas.md §31): cFile.Save on an empty model produces a .sdb that
cFile.OpenFile then REJECTS (ret=1) AND that pops a modal SAP dialog blocking the OAPI.
The bridge refuses to write that irreparable artifact rather than producing it silently.
Build geometry first (1h.2+ primitives), then save. Client-fixable."""

# Bridge internals
PYTHONNET_UNAVAILABLE = "pythonnet_unavailable"
"""pythonnet / the SAP2000v1 assembly could not be loaded. The bridge cannot talk
to SAP without it."""

ASSEMBLY_NOT_FOUND = "assembly_not_found"
"""SAP2000v1.dll was not found at the configured or auto-resolved path."""
