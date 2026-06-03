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

logger = logging.getLogger("sap_bridge.bridge_state")


def _session_error(code: str, message: str) -> Exception:
    """Build a SapSessionError lazily (avoids a circular import with sap_session, which
    instantiates the session singleton at module load and needs WorkspaceState)."""
    from .sap_session import SapSessionError

    return SapSessionError(code, message)

_WORKSPACE_SUFFIX = "__workspace"


@dataclass
class WorkspaceState:
    """Session-persistent workspace tracking. All fields mutable across the session.

    ``base_model_path`` is Optional because a blank model (created in memory, Fase 1h.1)
    has no base file. ``sap_instance_origin`` is preparatory for a future launch_sap
    (today always 'attached'): it lets a future teardown decide whether to close SAP
    (launched = ours) or leave it (attached = the user's). ``session_id`` (a UUID assigned
    on first attach) anchors the temp workspace dir for blank models and lets a future
    cleanup target this session's files.
    """

    base_model_path: Optional[str] = None
    workspace_path: Optional[str] = None
    sap_instance_origin: Literal["attached", "launched"] = "attached"
    session_id: Optional[str] = None


def _compute_workspace_path(base_path: Optional[str], session_id: Optional[str] = None) -> str:
    """Derive the workspace path. Pure function (input → output, no side effects beyond
    creating the temp dir for the blank case).

    - With a base: ``<base_dir>/<base_name>__workspace.sdb`` (the 1g.9 case).
    - Without a base (blank model, Fase 1h.1): a per-session temp file
      ``%TEMP%/sap_bridge_sessions/<session_id>/blank_workspace.sdb``.
    """
    if base_path is not None:
        base_dir = os.path.dirname(base_path)
        base_name = os.path.splitext(os.path.basename(base_path))[0]
        return os.path.join(base_dir, f"{base_name}{_WORKSPACE_SUFFIX}.sdb")

    import tempfile

    sid = session_id or "default"
    temp_root = os.path.join(tempfile.gettempdir(), "sap_bridge_sessions", sid)
    os.makedirs(temp_root, exist_ok=True)
    return os.path.join(temp_root, "blank_workspace.sdb")


def _is_workspace_path(path: str) -> bool:
    """True if ``path`` is a bridge workspace file."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.endswith(_WORKSPACE_SUFFIX)


def _loaded_path_or_none(sap_model: Any) -> Optional[str]:
    """The loaded model's absolute path, or None if there is no on-disk model.

    SAP returns a NON-absolute placeholder when no real file is loaded: ``''`` (SAP open
    with nothing) or ``'(Untitled)'`` (a model in memory, e.g. after InitializeNewModel,
    §30). Both map to None — "no base file".
    """
    loaded = sap_model.GetModelFilename(True)
    if not loaded or not os.path.isabs(loaded):
        return None
    return loaded


def ensure_workspace_from_current_model(sap_model: Any, state: WorkspaceState) -> bool:
    """Register the loaded model as the base, derive the workspace, and Save into it.

    GENERIC entry point (first-attach, open_model; new_from_template/launch_sap in future).
    After this the loaded model IS the workspace and the base is frozen. Returns True if a
    workspace was established, False if there is no on-disk model to anchor to (SAP open
    without a model — the attach handles that gracefully, awaiting new_blank_model/open_model).

    Idempotent-ish: if already on a workspace with a known base, it's a no-op.
    """
    loaded = _loaded_path_or_none(sap_model)
    if loaded is None:
        return False

    if _is_workspace_path(loaded) and state.base_model_path:
        # Already operating on our workspace and the base is known — nothing to do.
        return True

    # The loaded model is a (base) file the user opened. Freeze it as the base, derive the
    # workspace, and Save into the workspace so all subsequent writes land there.
    base_path = loaded
    workspace_path = _compute_workspace_path(base_path)
    sret = sap_model.File.Save(workspace_path)  # NOT Save_2 — it does not exist (§18)
    if sret != 0:
        raise _session_error(
            error_codes.OAPI_CALL_FAILED,
            f"could not create workspace via cFile.Save('{workspace_path}'): returned {sret}",
        )
    now = sap_model.GetModelFilename(True)
    if now.lower() != workspace_path.lower():
        raise _session_error(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"workspace Save reported 0 but loaded path is '{now}', not '{workspace_path}'",
        )
    state.base_model_path = base_path
    state.workspace_path = workspace_path
    logger.info("Workspace ready. Base: %s. Workspace: %s", base_path, workspace_path)
    return True


def ensure_workspace_for_blank(sap_model: Any, state: WorkspaceState) -> str:
    """Establish a workspace for a blank (in-memory) model: base stays None, the workspace
    lives in a per-session temp dir. Used by new_blank_model. Returns the workspace path.

    The model must already be initialized in memory (InitializeNewModel). This Saves it to
    the temp workspace so subsequent writes land there.
    """
    workspace_path = _compute_workspace_path(None, state.session_id)
    sret = sap_model.File.Save(workspace_path)  # NOT Save_2 (§18)
    if sret != 0:
        raise _session_error(
            error_codes.OAPI_CALL_FAILED,
            f"could not create blank workspace via cFile.Save('{workspace_path}'): {sret}",
        )
    now = sap_model.GetModelFilename(True)
    if now.lower() != workspace_path.lower():
        raise _session_error(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"blank workspace Save reported 0 but loaded path is '{now}'",
        )
    state.base_model_path = None  # no base file for a blank model
    state.workspace_path = workspace_path
    logger.info("Blank workspace ready. Base: None. Workspace: %s", workspace_path)
    return workspace_path


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
        raise _session_error(
            error_codes.OAPI_CALL_FAILED,
            f"could not re-anchor to workspace via OpenFile('{state.workspace_path}'): "
            f"returned {oret}",
        )
