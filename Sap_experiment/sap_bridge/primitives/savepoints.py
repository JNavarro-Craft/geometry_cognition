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


def _model_paths(sap_model: Any) -> tuple[str, str, str]:
    """Return (original_model_path, model_dir, model_name) for the loaded model.

    Raises NO_MODEL_OPEN if the model has no on-disk path (a never-saved new model).
    """
    path = sap_model.GetModelFilename(True)
    if not path or not os.path.isabs(path):
        raise SapSessionError(
            error_codes.NO_MODEL_OPEN,
            "the open model has no saved path; save it in SAP before using savepoints",
        )
    model_dir = os.path.dirname(path)
    model_name = os.path.splitext(os.path.basename(path))[0]
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


def create_savepoint(sap_model: Any, name: str, dry_run: bool) -> SavepointCreateResponse:
    """Save the current model state to a savepoint .sdb file.

    Refuses with SAVEPOINT_ALREADY_EXISTS if the target file exists (no silent overwrite).
    In dry-run, returns the target path + writability + estimated size without writing.
    Audited (write_side_design.md logging).
    """
    with audited("create_savepoint", {"name": name, "dry_run": dry_run}) as ctx:
        original, model_dir, model_name = _model_paths(sap_model)
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
            # Estimate size from the current model file (the savepoint is a copy of it).
            est = os.path.getsize(original) if os.path.exists(original) else 0
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"target_path": sp_path, "estimated_size_bytes": est}
            return SavepointCreateResponse(
                dry_run=True,
                validation_passed=True,
                would_apply=_info(name, sp_path, size_override=est),
            )

        # Real write. Save acts like Save As (it repoints the in-memory model), so save to
        # the savepoint and then reopen the original to leave the session on the user's model.
        sret = sap_model.File.Save(sp_path)
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.Save('{sp_path}') returned {sret}",
            )
        oret = sap_model.File.OpenFile(original)
        if oret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"savepoint written but reopening the original returned {oret}; the session "
                f"may be pointing at the savepoint ({sp_path}) — reopen {original} in SAP",
            )
        if not os.path.exists(sp_path):
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"cFile.Save returned 0 but no file appeared at {sp_path}",
            )
        ctx["result_details"] = {"path": sp_path, "size_bytes": os.path.getsize(sp_path)}
        return SavepointCreateResponse(dry_run=False, applied=_info(name, sp_path))


def restore_savepoint(
    sap_model: Any, name: str, confirm: bool, dry_run: bool
) -> SavepointRestoreResponse:
    """Restore a savepoint, replacing the loaded model with it.

    Destructive (it replaces the current model), so confirm=true is mandatory unless
    dry_run. Refuses with SAVEPOINT_NOT_FOUND if the file is missing. The cSapModel handle
    stays valid after OpenFile, so no re-attach is needed.
    """
    with audited(
        "restore_savepoint", {"name": name, "confirm": confirm, "dry_run": dry_run}
    ) as ctx:
        _original, model_dir, model_name = _model_paths(sap_model)
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
                f"restore_savepoint('{name}') replaces the loaded model with the savepoint "
                "and discards unsaved changes; pass confirm=true to proceed",
            )

        oret = sap_model.File.OpenFile(sp_path)
        if oret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.OpenFile('{sp_path}') returned {oret}",
            )
        model_file = sap_model.GetModelFilename(True)
        ctx["result_details"] = {"restored_from": sp_path, "model_file": model_file}
        return SavepointRestoreResponse(dry_run=False, restored_from=info, model_file=model_file)
