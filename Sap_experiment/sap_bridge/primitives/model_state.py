"""Model state primitives: lock management and open_model (Fase 1g.8).

State-level operations that make the iterative write→analyze→write loop robust — the two
USE blockers §26 found. Distinct from model_settings (configurable settings like DOFs/units):

  * set_model_locked — escape the locked state SAP enters after run_analysis, so the client
    can keep modifying. The bridge does NOT auto-unlock on other writes (predictable
    primitives); the client calls this explicitly. Idempotent.
  * open_model — replace the loaded model (recover the base after restore, switch models).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §27):

  * cSapModel.SetModelIsLocked(Boolean) → 0 OK, idempotent (setting the current value again
    returns 0). cSapModel.GetModelIsLocked() → bool.
  * cFile.OpenFile(String) → 0 OK. ⚠️ With a NON-EXISTENT path it returns ret=1 BUT leaves
    the session pointing at the phantom path (GetModelFilename changes). So open_model
    validates the path on the FILESYSTEM before calling OpenFile — never lets SAP enter
    that bad state. OpenFile DISCARDS unsaved changes silently (the client must savepoint).
    The cSapModel handle stays valid after OpenFile (§18) — no re-attach.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    ModelLockChange,
    ModelOpenChange,
    OpenModelResponse,
    SetModelLockedResponse,
)
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.model_state")


def set_model_locked(sap_model: Any, locked: bool, dry_run: bool, confirm: bool) -> SetModelLockedResponse:
    """Set the model lock state. Confirm-gated (global state), dry-run-capable, idempotent."""
    with audited("set_model_locked", {"locked": locked, "dry_run": dry_run, "confirm": confirm}) as ctx:
        current = bool(sap_model.GetModelIsLocked())

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"current_locked": current, "new_locked": locked}
            return SetModelLockedResponse(
                dry_run=True, validation_passed=True,
                would_apply=ModelLockChange(current_locked=current, new_locked=locked),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "set_model_locked changes a global model state (lock); pass confirm=true to apply",
            )

        ret = sap_model.SetModelIsLocked(locked)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cSapModel.SetModelIsLocked({locked}) returned {ret_code}",
            )
        now = bool(sap_model.GetModelIsLocked())  # read back (M2)
        ctx["result_details"] = {"previous_locked": current, "current_locked": now}
        return SetModelLockedResponse(
            dry_run=False,
            applied=ModelLockChange(previous_locked=current, current_locked=now),
        )


def open_model(sap_model_getter: Any, state: Any, path: str, dry_run: bool, confirm: bool) -> OpenModelResponse:
    """Open a model, replacing the loaded one. The opened model becomes the new BASE: after
    OpenFile, the bridge derives a fresh workspace from it and re-anchors there (so the
    bridge keeps operating on a transient copy, never on the just-opened base — §3c).

    ``sap_model_getter`` is a callable returning the live cSapModel. ``state`` is the
    WorkspaceState. Validates the path (absolute, .sdb, exists) BEFORE OpenFile — SAP would
    otherwise leave the session on a phantom path (§27). Confirm-gated.
    """
    from ..bridge_state import ensure_workspace_from_current_model

    with audited("open_model", {"path": path, "dry_run": dry_run, "confirm": confirm}) as ctx:
        sap_model = sap_model_getter()
        current_path = sap_model.GetModelFilename(True)

        # Path validation — the bridge's responsibility (avoid SAP's phantom-path state).
        if not os.path.isabs(path) or not path.lower().endswith(".sdb"):
            raise SapSessionError(
                error_codes.INVALID_PATH,
                f"path must be an absolute .sdb path; got '{path}'",
            )
        if not os.path.isfile(path):
            raise SapSessionError(
                error_codes.FILE_NOT_FOUND,
                f"no file at '{path}' (open_model checks existence before opening)",
            )

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"current_model_path": current_path, "new_model_path": path}
            return OpenModelResponse(
                dry_run=True, validation_passed=True,
                would_apply=ModelOpenChange(current_model_path=current_path, new_model_path=path),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "open_model replaces the loaded model and discards unsaved changes; "
                "pass confirm=true to proceed",
            )

        ret = sap_model.File.OpenFile(path)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.OpenFile('{path}') returned {ret_code}",
            )
        # The opened model is the new base. Re-derive a fresh workspace from it (this also
        # resets state.base_model_path / workspace_path) so subsequent writes never touch it.
        state.base_model_path = None  # force re-derivation from the just-opened (non-workspace) file
        ensure_workspace_from_current_model(sap_model_getter(), state)
        # Handle stays valid after OpenFile (§18); read the final (workspace) path (M2).
        now_path = sap_model_getter().GetModelFilename(True)
        ctx["result_details"] = {"previous_model_path": current_path, "current_model_path": now_path}
        return OpenModelResponse(
            dry_run=False,
            applied=ModelOpenChange(previous_model_path=current_path, current_model_path=now_path),
        )
