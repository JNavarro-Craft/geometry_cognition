"""save_workspace_as — materialize the workspace to disk as a new base (Fase 1h.1).

Closes the build-from-blank cycle: after building a model on a (blank or normal) workspace,
save_workspace_as writes the current content to a chosen path, promotes that path to the new
immutable base, and re-anchors onto a fresh workspace alongside it — so the normal workspace
pattern (reset_workspace, savepoints, ...) resumes from there.

Design (write_side_design §3d): the actual Save + re-anchor lives in the shared helper
``workspace._save_to_path_and_update_state(path, allow_base_overwrite)``. save_workspace_as
calls it with ``allow_base_overwrite=False`` and explicitly PROHIBITS ``path == current base``
— writing the base is a different primitive (commit_workspace_to_base, future), built on the
same helper with the flag inverted. Policy checks (path validity, overwrite confirm) live here.

OAPI note: cFile.Save(path) → 0 OK, creates the file (verified §30). There is no Save_2 (§18).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..bridge_state import WorkspaceState, _compute_workspace_path
from ..contracts import SaveWorkspaceAsChange, SaveWorkspaceAsResponse
from ..sap_session import SapSessionError
from .workspace import _save_to_path_and_update_state

logger = logging.getLogger("sap_bridge.primitives.persistence")


def save_workspace_as(
    sap_model: Any, state: WorkspaceState, path: str, dry_run: bool, confirm: bool
) -> SaveWorkspaceAsResponse:
    """Save the current workspace content to ``path`` as a new base.

    Validates ``path`` (absolute .sdb), PROHIBITS ``path == current base`` (INVALID_PATH —
    that is commit_workspace_to_base's job), and REQUIRES ``confirm`` only to OVERWRITE an
    existing file. ``dry_run`` previews. Raises INVALID_PATH, CONFIRM_REQUIRED, OAPI_CALL_FAILED.
    """
    with audited("save_workspace_as", {"path": path, "dry_run": dry_run, "confirm": confirm}) as ctx:
        if not os.path.isabs(path) or not path.lower().endswith(".sdb"):
            raise SapSessionError(
                error_codes.INVALID_PATH,
                f"path must be an absolute .sdb path; got '{path}'",
            )
        # Prohibit writing the current base — that is a commit, a separate future primitive.
        if state.base_model_path and os.path.normcase(path) == os.path.normcase(state.base_model_path):
            raise SapSessionError(
                error_codes.INVALID_PATH,
                f"path '{path}' is the current base model; save_workspace_as cannot overwrite the "
                "base (that is commit_workspace_to_base, a future primitive). Choose another path.",
            )
        # Also reject the current workspace path itself (it is bridge-managed, not a base target).
        if state.workspace_path and os.path.normcase(path) == os.path.normcase(state.workspace_path):
            raise SapSessionError(
                error_codes.INVALID_PATH,
                f"path '{path}' is the bridge's own workspace file; choose a real base path",
            )

        overwrote_existing = os.path.isfile(path)
        previous_base = state.base_model_path
        new_workspace = _compute_workspace_path(path)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {
                "new_base_model_path": path,
                "new_workspace_path": new_workspace,
                "overwrote_existing": overwrote_existing,
            }
            return SaveWorkspaceAsResponse(
                dry_run=True,
                would_apply=SaveWorkspaceAsChange(
                    previous_base_model_path=previous_base,
                    new_base_model_path=path,
                    new_workspace_path=new_workspace,
                    overwrote_existing=overwrote_existing,
                ),
            )

        # confirm is mandatory ONLY to overwrite an existing file (M1: SetX/Save overwrite
        # silently by path). Saving to a fresh path needs no confirm (non-destructive).
        if overwrote_existing and not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"a file already exists at '{path}'; pass confirm=true to overwrite it",
            )

        actual_workspace = _save_to_path_and_update_state(
            sap_model, state, path, allow_base_overwrite=False
        )
        ctx["result_details"] = {
            "new_base_model_path": path,
            "new_workspace_path": actual_workspace,
            "overwrote_existing": overwrote_existing,
        }
        return SaveWorkspaceAsResponse(
            dry_run=False,
            applied=SaveWorkspaceAsChange(
                previous_base_model_path=previous_base,
                new_base_model_path=path,
                new_workspace_path=actual_workspace,
                overwrote_existing=overwrote_existing,
            ),
        )
