"""Savepoints — the write-side's undo infrastructure (Fase 1g.1).

The FIRST primitives that write. They write to the FILESYSTEM (separate .sdb files), not
to the SAP model in memory: a savepoint is a copy of the model the client can restore
later. The rest of the write-side (set_active_dof, create_section, …) builds on these for
rollback. Governed by docs/write_side_design.md.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §18):

  * cFile.Save_2 does NOT exist in this assembly — only ``cFile.Save(String FileName)``.
    The design doc named Save_2; the real call is Save. Returns 0 on success.
  * ⚠️ Save acts like "Save As": after Save(path) the in-memory model's filename POINTS AT
    the new path (GetModelFilename returns it). So create_savepoint must Save to the
    savepoint path and then OpenFile the ORIGINAL again, leaving the session pointing back
    at the user's model — otherwise the user would be silently working in the savepoint.
  * cFile.OpenFile(String FileName) loads a model, replacing the current one, returns 0.
    The existing cSapModel handle stays VALID after OpenFile (same SAP process, new model)
    — no re-attach needed; GetModelIsLocked answers and GetModelFilename reflects the new
    path. restore_savepoint relies on this.
  * cSapModel.GetModelFilename(IncludePath: bool) -> str (absolute path when True).

list_savepoints is a pure filesystem scan (no OAPI) — it works even with SAP not attached.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    SavepointCreateResponse,
    SavepointInfo,
    SavepointListResponse,
    SavepointRestoreResponse,
)
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.savepoints")

_SP_INFIX = "__sp_"


def _base_model_name(stem: str) -> str:
    """Strip any bridge-reserved suffix (``__sp_*`` chain or ``__workspace``) from a filename
    stem to recover the BASE model name.

    The session loads on ``<base>__workspace.sdb`` (Fase 1g.9) or, transiently, on a
    ``<base>__sp_<name>.sdb`` — without stripping, a create/restore would build names against
    the workspace/savepoint and nest (``__sp_X__sp_Y`` — §26). Cutting at the FIRST reserved
    suffix recovers the base in every case: ``TEST_01``→``TEST_01``;
    ``TEST_01__workspace``→``TEST_01``; ``TEST_01__sp_v1__sp_v2``→``TEST_01``. ``__sp_`` and
    ``__workspace`` are bridge-reserved (write_side_design.md; a model legitimately named
    with them would be misread — known limitation).
    """
    candidates = [stem.find(_SP_INFIX), stem.find("__workspace")]
    cuts = [c for c in candidates if c != -1]
    return stem[: min(cuts)] if cuts else stem


def _model_paths(sap_model: Any) -> tuple[str, str, str]:
    """Return (loaded_path, model_dir, base_model_name) for the loaded model.

    ``loaded_path`` is the file the session is actually on (may be a ``__sp_*`` savepoint
    after a restore); ``base_model_name`` strips any ``__sp_*`` chain so savepoint names
    are always built against the BASE model and never nest (§26 fix). Raises NO_MODEL_OPEN
    if the model has no on-disk path (a never-saved new model).
    """
    path = sap_model.GetModelFilename(True)
    if not path or not os.path.isabs(path):
        raise SapSessionError(
            error_codes.NO_MODEL_OPEN,
            "the open model has no saved path; save it in SAP before using savepoints",
        )
    model_dir = os.path.dirname(path)
    model_name = _base_model_name(os.path.splitext(os.path.basename(path))[0])
    return path, model_dir, model_name


def _savepoint_path(model_dir: str, model_name: str, name: str) -> str:
    return os.path.join(model_dir, f"{model_name}{_SP_INFIX}{name}.sdb")


def _info(name: str, path: str, *, size_override: int | None = None) -> SavepointInfo:
    """Build a SavepointInfo from a file on disk (or an estimated size for dry-run)."""
    size = size_override if size_override is not None else os.path.getsize(path)
    # ctime is creation time on Windows; relay it as an ISO-8601 UTC fact.
    ts = os.path.getctime(path) if os.path.exists(path) else datetime.now(timezone.utc).timestamp()
    created = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return SavepointInfo(name=name, path=path, created_at=created, size_bytes=size)


def list_savepoints(sap_model: Any) -> SavepointListResponse:
    """List the savepoints for the current model (filesystem scan; empty list if none)."""
    _path, model_dir, model_name = _model_paths(sap_model)
    prefix = f"{model_name}{_SP_INFIX}"
    found: list[SavepointInfo] = []
    for entry in sorted(os.listdir(model_dir)):
        if entry.startswith(prefix) and entry.endswith(".sdb"):
            sp_name = entry[len(prefix):-len(".sdb")]
            found.append(_info(sp_name, os.path.join(model_dir, entry)))
    return SavepointListResponse(model_name=model_name, count=len(found), savepoints=found)


def create_savepoint(sap_model: Any, state: Any, name: str, dry_run: bool) -> SavepointCreateResponse:
    """Save the current workspace state to a savepoint .sdb file, then re-anchor to the
    workspace. ``state`` is the WorkspaceState (savepoint names resolve against the base;
    the session returns to the workspace after — §3c). Refuses with SAVEPOINT_ALREADY_EXISTS
    if the target exists. Audited.
    """
    from ..bridge_state import reanchor_to_workspace

    with audited("create_savepoint", {"name": name, "dry_run": dry_run}) as ctx:
        # ``loaded`` = the file the session is on now (the workspace). ``model_name`` is the
        # BASE name (stripped of any __sp_*/__workspace), so the savepoint name never nests.
        loaded, model_dir, model_name = _model_paths(sap_model)
        sp_path = _savepoint_path(model_dir, model_name, name)

        if os.path.exists(sp_path):
            raise SapSessionError(
                error_codes.SAVEPOINT_ALREADY_EXISTS,
                f"savepoint '{name}' already exists at {sp_path}; use a different name "
                "(delete is not implemented this phase)",
            )

        if dry_run:
            if not os.access(model_dir, os.W_OK):
                raise SapSessionError(
                    error_codes.DRY_RUN_VALIDATION_FAILED,
                    f"savepoint directory is not writable: {model_dir}",
                )
            est = os.path.getsize(loaded) if os.path.exists(loaded) else 0
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"target_path": sp_path, "estimated_size_bytes": est}
            return SavepointCreateResponse(
                dry_run=True,
                validation_passed=True,
                would_apply=_info(name, sp_path, size_override=est),
            )

        # Save acts like Save As (repoints the loaded model to the savepoint), so Save then
        # re-anchor to the workspace (§3c) — the session always ends on the workspace.
        sret = sap_model.File.Save(sp_path)
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.Save('{sp_path}') returned {sret}",
            )
        if not os.path.exists(sp_path):
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"cFile.Save returned 0 but no file appeared at {sp_path}",
            )
        reanchor_to_workspace(sap_model, state)
        ctx["result_details"] = {"path": sp_path, "size_bytes": os.path.getsize(sp_path)}
        return SavepointCreateResponse(dry_run=False, applied=_info(name, sp_path))


def restore_savepoint(
    sap_model: Any, state: Any, name: str, confirm: bool, dry_run: bool
) -> SavepointRestoreResponse:
    """Restore a savepoint into the workspace. ``state`` is the WorkspaceState.

    Opens the savepoint, then Saves it into the workspace (overwriting it) and leaves the
    session ON the workspace (§3c) — so the session always operates on the transient
    workspace, never on the savepoint file directly. Destructive → confirm mandatory unless
    dry_run. Refuses with SAVEPOINT_NOT_FOUND if missing.
    """
    with audited(
        "restore_savepoint", {"name": name, "confirm": confirm, "dry_run": dry_run}
    ) as ctx:
        _loaded, model_dir, model_name = _model_paths(sap_model)
        sp_path = _savepoint_path(model_dir, model_name, name)

        if not os.path.exists(sp_path):
            raise SapSessionError(
                error_codes.SAVEPOINT_NOT_FOUND,
                f"savepoint '{name}' not found at {sp_path} (list with GET /v1/savepoints)",
            )
        info = _info(name, sp_path)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"would_replace_with": sp_path}
            return SavepointRestoreResponse(dry_run=True, would_replace_with=info)

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"restore_savepoint('{name}') replaces the workspace with the savepoint "
                "and discards unsaved changes; pass confirm=true to proceed",
            )

        # Open the savepoint, then Save its content into the workspace and stay there.
        oret = sap_model.File.OpenFile(sp_path)
        if oret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.OpenFile('{sp_path}') returned {oret}",
            )
        if state.workspace_path:
            sret = sap_model.File.Save(state.workspace_path)
            if sret != 0:
                raise SapSessionError(
                    error_codes.OAPI_CALL_FAILED,
                    f"restored savepoint but Save to workspace returned {sret}",
                )
        model_file = sap_model.GetModelFilename(True)
        ctx["result_details"] = {"restored_from": sp_path, "model_file": model_file}
        return SavepointRestoreResponse(dry_run=False, restored_from=info, model_file=model_file)
