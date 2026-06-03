"""Workspace state tracking + helpers (Fase 1g.9, write_side_design.md §3c).

Resolves §28: the bridge operates on a TRANSIENT workspace copy, never on the user's base
model file (in the default flow). The base stays byte-immutable; the workspace is
regenerable.

State lives on the SapSession (one process == one session). The helpers here are written
GENERIC on purpose (future-aware design): the same auto-workspace / re-anchor machinery
must serve not just the first attach but future origins of a base — open_model (this
phase), and later new_from_template, new_blank_model, launch_sap. So they take the live
cSapModel and the state object, and assume only "there is a loaded model".
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from . import error_codes
from .sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.bridge_state")

_WORKSPACE_SUFFIX = "__workspace"


@dataclass
class WorkspaceState:
    """Session-persistent workspace tracking. All fields mutable across the session.

    ``base_model_path`` is Optional because a future blank model (created in memory) would
    have no base file. ``sap_instance_origin`` is preparatory for a future launch_sap
    (today always 'attached'): it lets a future teardown decide whether to close SAP
    (launched = ours) or leave it (attached = the user's).
    """

    base_model_path: Optional[str] = None
    workspace_path: Optional[str] = None
    sap_instance_origin: Literal["attached", "launched"] = "attached"


def _compute_workspace_path(base_path: str) -> str:
    """Derive the workspace path from a base model path.

    Isolated so a future variant (e.g. a dedicated session dir under %TEMP% for read-only
    base dirs or blank models) can replace it without touching callers. Today:
    ``<base_dir>/<base_name>__workspace.sdb``.
    """
    base_dir = os.path.dirname(base_path)
    base_name = os.path.splitext(os.path.basename(base_path))[0]
    return os.path.join(base_dir, f"{base_name}{_WORKSPACE_SUFFIX}.sdb")


def _is_workspace_path(path: str) -> bool:
    """True if ``path`` is a bridge workspace file."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.endswith(_WORKSPACE_SUFFIX)


def ensure_workspace_from_current_model(sap_model: Any, state: WorkspaceState) -> None:
    """Register the loaded model as the base, derive the workspace, and Save into it.

    GENERIC entry point (used by first-attach today; by open_model, new_from_template,
    new_blank_model, launch_sap in the future). Assumes only: there is a loaded model with
    an on-disk path. After this call the loaded model IS the workspace, and the base is
    frozen.

    Idempotent-ish: if the loaded model is already a workspace (re-attach within a session),
    it does not re-derive from the workspace name — it keeps the registered base.
    """
    loaded = sap_model.GetModelFilename(True)
    if not loaded or not os.path.isabs(loaded):
        raise SapSessionError(
            error_codes.NO_MODEL_OPEN,
            "the open model has no saved path; save it in SAP before the bridge can "
            "create a workspace",
        )

    if _is_workspace_path(loaded) and state.base_model_path:
        # Already operating on our workspace and the base is known — nothing to do.
        return

    # The loaded model is a (base) file the user opened. Freeze it as the base, derive the
    # workspace, and Save into the workspace so all subsequent writes land there.
    base_path = loaded
    workspace_path = _compute_workspace_path(base_path)
    sret = sap_model.File.Save(workspace_path)  # NOT Save_2 — it does not exist (§18)
    if sret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"could not create workspace via cFile.Save('{workspace_path}'): returned {sret}",
        )
    now = sap_model.GetModelFilename(True)
    if now.lower() != workspace_path.lower():
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"workspace Save reported 0 but loaded path is '{now}', not '{workspace_path}'",
        )
    state.base_model_path = base_path
    state.workspace_path = workspace_path
    logger.info("Workspace ready. Base: %s. Workspace: %s", base_path, workspace_path)


def reanchor_to_workspace(sap_model: Any, state: WorkspaceState) -> None:
    """Bring the loaded model back to the workspace after a primitive moved it elsewhere.

    Shared by savepoints (which Save/OpenFile a savepoint file) and open_model. Resolves
    §19 proactively: the loaded model is ALWAYS the workspace after any operation. A no-op
    if the loaded model is already the workspace.
    """
    if not state.workspace_path:
        return  # No workspace established yet (should not happen post-attach).
    loaded = sap_model.GetModelFilename(True)
    if loaded.lower() == state.workspace_path.lower():
        return
    oret = sap_model.File.OpenFile(state.workspace_path)
    if oret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"could not re-anchor to workspace via OpenFile('{state.workspace_path}'): "
            f"returned {oret}",
        )
