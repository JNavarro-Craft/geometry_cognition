"""new_blank_model — initialize an empty SAP model from scratch (Fase 1h.1).

Opens the build-from-blank cycle (1h.*): InitializeNewModel makes an empty model in
memory; the bridge then establishes a transient workspace in a per-session temp dir
(base_model_path stays None — there is no base file yet). Subsequent build primitives
(geometry, sections, loads — phases 1h.2+) operate on that workspace as usual.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §30):

  * cSapModel.InitializeNewModel(eUnits) → 0 OK, takes the units enum member (resolve by
    name off the live enum, anti-pattern #5). It DISCARDS the currently loaded model
    silently → confirm is the only protection against losing work.
  * After init, GetModelFilename returns '(Untitled)' (a placeholder, not a path) and the
    model has 0 joints / 0 frames. Units are NOT anchored — set_present_units can change
    them later. cFile.Save on the in-memory model works (creates the file).
"""
from __future__ import annotations

from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..bridge_state import _compute_workspace_path, ensure_workspace_for_blank
from ..contracts import BlankModelChange, NewBlankModelResponse
from ..sap_session import SapSessionError
from . import units as units_primitive


def _initialize_from(sap_model: Any, source: str, units_member: Any) -> None:
    """Initialize the model from ``source``. Today source='blank' (InitializeNewModel +
    File.NewBlank); a future new_from_template would pass a template path here (OpenFile + keep
    base None). The seam keeps that extension natural (write_side_design §3d).

    ⚠️ §32: InitializeNewModel ALONE does NOT leave a buildable model — AddCartesian/AddByPoint
    return 1 and nothing is added, and Save produces a .sdb that OpenFile rejects (§31). The
    model becomes buildable only after cFile.NewBlank(). This is the root cause of §31; the
    empty_model guard in save_workspace_as stays as a secondary defense."""
    if source == "blank":
        ret = sap_model.InitializeNewModel(units_member)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cSapModel.InitializeNewModel returned {ret_code}",
            )
        # NewBlank() is what makes the model actually buildable (§32). Without it the model is
        # initialized-but-inert: geometry adds fail and Save yields an unreopenable .sdb.
        nret = sap_model.File.NewBlank()
        nret_code = nret[0] if isinstance(nret, tuple) else nret
        if nret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cFile.NewBlank returned {nret_code}",
            )
    else:  # pragma: no cover - future new_from_template
        raise SapSessionError(error_codes.OAPI_UNEXPECTED_SHAPE, f"unknown init source '{source}'")


def new_blank_model(
    sap_model: Any, oapi_namespace: Any, state: Any, units: str, dry_run: bool, confirm: bool
) -> NewBlankModelResponse:
    """Initialize an empty model with ``units`` and set up a temp workspace.

    Destructive (discards the loaded model, no save) → confirm mandatory. Raises
    UNKNOWN_UNIT_SYSTEM for a bad units name, CONFIRM_REQUIRED, OAPI_CALL_FAILED.
    """
    with audited("new_blank_model", {"units": units, "dry_run": dry_run, "confirm": confirm}) as ctx:
        units_member = units_primitive.resolve_unit_system(oapi_namespace, units)
        if units_member is None:
            supported = ", ".join(units_primitive.unit_system_names(oapi_namespace))
            raise SapSessionError(
                error_codes.UNKNOWN_UNIT_SYSTEM,
                f"unknown unit system '{units}'; supported: {supported}",
            )

        new_ws = _compute_workspace_path(None, state.session_id)
        prev_loaded = sap_model.GetModelFilename(True) or "none"

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"new_units": units, "new_workspace_path": new_ws}
            return NewBlankModelResponse(
                dry_run=True,
                would_apply=BlankModelChange(
                    previous_loaded=prev_loaded,
                    new_units=units,
                    new_base_model_path=None,
                    new_workspace_path=new_ws,
                ),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "new_blank_model discards the currently loaded model (no save); "
                "pass confirm=true to proceed",
            )

        _initialize_from(sap_model, "blank", units_member)
        workspace_path = ensure_workspace_for_blank(sap_model, state)  # base stays None
        ctx["result_details"] = {"new_units": units, "workspace_path": workspace_path}
        return NewBlankModelResponse(
            dry_run=False,
            applied=BlankModelChange(
                previous_loaded=prev_loaded,
                new_units=units,
                new_base_model_path=None,
                new_workspace_path=workspace_path,
            ),
        )
