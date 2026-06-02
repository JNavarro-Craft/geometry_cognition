"""set_present_units — second global-setting write (Fase 1g.3).

Follows the set_active_dof template exactly: validate → dry_run → confirm → apply → audit.
Changing present units is a DISPLAY preference — it reformats how the read-side reports
values (distances stay metres; forces/moments rescale, e.g. kgf → N ≈ ×9.80665) — not a
data conversion. The bridge does not convert anything itself; it sets the unit system and
the read-side then reports consistently in it.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §22):

  * cSapModel.SetPresentUnits(eUnits Units) → takes the eUnits ENUM MEMBER (a bare int
    raises TypeError), returns 0 on success. The name → member resolution lives in
    units.resolve_unit_system (getattr on the live enum), so the accepted set is exactly
    the read-side's set — no duplicated table.
  * ⚠️ The eUnits codes are not what the phase prompt assumed: N_m_C is 10, not 7 (7 is
    kgf_mm_C). Resolving by name off the live enum avoids that whole class of mistake.
  * Changing present units does NOT change model_is_locked (display preference). Echoed.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import SetPresentUnitsResponse, UnitsChange
from ..sap_session import SapSessionError
from . import units as units_primitive

logger = logging.getLogger("sap_bridge.primitives.present_units")


def set_present_units(
    sap_model: Any, oapi_namespace: Any, units: str, dry_run: bool, confirm: bool
) -> SetPresentUnitsResponse:
    """Set the model's present (display) units by NAME. Confirm-gated, dry-run-capable.

    Raises UNKNOWN_UNIT_SYSTEM for an unknown name, CONFIRM_REQUIRED if applying without
    confirm, OAPI_CALL_FAILED if SetPresentUnits fails.
    """
    with audited(
        "set_present_units", {"units": units, "dry_run": dry_run, "confirm": confirm}
    ) as ctx:
        target_member = units_primitive.resolve_unit_system(oapi_namespace, units)
        if target_member is None:
            supported = ", ".join(units_primitive.unit_system_names(oapi_namespace))
            raise SapSessionError(
                error_codes.UNKNOWN_UNIT_SYSTEM,
                f"unknown unit system '{units}'; supported names: {supported}",
            )

        current = units_primitive.get_present_units(sap_model)
        new_units = units_primitive._units_response(target_member)
        summary = f"{current.present_units} → {new_units.present_units}"

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"change_summary": summary}
            return SetPresentUnitsResponse(
                dry_run=True,
                validation_passed=True,
                would_apply=UnitsChange(
                    current_units=current, new_units=new_units, change_summary=summary
                ),
                model_is_locked=bool(sap_model.GetModelIsLocked()),
            )

        # Global setting → confirm mandatory (write_side_design.md §5.3).
        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "set_present_units changes a global model setting (present units); "
                "pass confirm=true to apply",
            )

        sret = sap_model.SetPresentUnits(target_member)
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"cSapModel.SetPresentUnits('{units}') returned {ret_code}",
            )

        applied_now = units_primitive.get_present_units(sap_model)
        ctx["result_details"] = {"change_summary": summary}
        return SetPresentUnitsResponse(
            dry_run=False,
            applied=UnitsChange(
                previous_units=current, current_units=applied_now, change_summary=summary
            ),
            model_is_locked=bool(sap_model.GetModelIsLocked()),
        )
