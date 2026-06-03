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

OAPI notes: cFile.Save(path) → 0 OK, creates the file (verified §30); there is no Save_2 (§18).
⚠️ But on a model with NO geometry, that .sdb is NOT reopenable — OpenFile rejects it (ret=1)
and pops a modal SAP dialog that blocks the whole OAPI until dismissed (§31). So this primitive
guards: a model with 0 joints and 0 frames is refused with EMPTY_MODEL before any disk write.
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

        # Empty-model guard (§31): cFile.Save on a model with no geometry produces a .sdb that
        # OpenFile then REJECTS (ret=1) and that pops a modal SAP dialog blocking the OAPI. Refuse
        # to write that irreparable artifact rather than producing it silently. Checked here (not
        # just on the real run) so dry_run reports it too — the client learns before committing.
        # NB (anti-patrón #5): cPointObj.Count() takes no args, but cFrameObj.Count(String) takes
        # a group name — "" means all frames. Verified by reflection against SAP26.
        n_joints = sap_model.PointObj.Count()
        n_frames = sap_model.FrameObj.Count("")
        if n_joints == 0 and n_frames == 0:
            raise SapSessionError(
                error_codes.EMPTY_MODEL,
                "the model has no joints and no frames; cFile.Save would produce a .sdb that SAP "
                "cannot reopen (verified §31). Build geometry first (1h.2+ primitives), then save.",
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
