"""reset_workspace — regenerate the transient workspace from the immutable base (Fase 1g.9).

Returns the session to a known clean baseline without relying on savepoints: reopen the
base, Save into the workspace, re-anchor. The base file is never written (write_side_design
§3c). See bridge_state.py for the workspace machinery.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..bridge_state import WorkspaceState
from ..contracts import ResetWorkspaceResponse, WorkspaceInfo
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.workspace")


def reset_workspace(sap_model: Any, state: WorkspaceState, dry_run: bool, confirm: bool) -> ResetWorkspaceResponse:
    """Reset the workspace to a clean copy of the base model.

    Raises NO_MODEL_OPEN if no base is registered (e.g. a future blank model with no base —
    the condition is made explicit here though that case does not exist this phase),
    CONFIRM_REQUIRED, OAPI_CALL_FAILED.
    """
    with audited("reset_workspace", {"dry_run": dry_run, "confirm": confirm}) as ctx:
        if not state.base_model_path or not state.workspace_path:
            raise SapSessionError(
                error_codes.NO_MODEL_OPEN,
                "no base model is registered; the workspace cannot be reset (a blank model "
                "without a base file is not supported this phase)",
            )

        info = WorkspaceInfo(
            base_model_path=state.base_model_path,
            workspace_path=state.workspace_path,
            sap_instance_origin=state.sap_instance_origin,
        )

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {
                "base_model_path": state.base_model_path,
                "workspace_path": state.workspace_path,
                "action": "reopen base then Save into workspace (discards workspace edits)",
            }
            return ResetWorkspaceResponse(dry_run=True, validation_passed=True, would_apply=info)

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "reset_workspace discards all workspace changes and reloads the clean base; "
                "pass confirm=true to proceed",
            )

        # Reopen the clean base, then Save into the workspace (overwriting it). The base file
        # itself is only READ here (OpenFile), never written.
        oret = sap_model.File.OpenFile(state.base_model_path)
        if oret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"reset_workspace: OpenFile('{state.base_model_path}') returned {oret}",
            )
        sret = sap_model.File.Save(state.workspace_path)
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"reset_workspace: Save('{state.workspace_path}') returned {sret}",
            )
        now = sap_model.GetModelFilename(True)
        if now.lower() != state.workspace_path.lower():
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"reset_workspace: loaded path is '{now}', expected workspace "
                f"'{state.workspace_path}'",
            )
        ctx["result_details"] = {"workspace_path": state.workspace_path}
        return ResetWorkspaceResponse(dry_run=False, applied=info)
