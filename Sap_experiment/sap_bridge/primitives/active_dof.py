"""set_active_dof — the first primitive that MUTATES the SAP model in memory (Fase 1g.2).

A global model setting (active DOFs), so under write_side_design.md §5.3 confirm is
mandatory. dry_run previews the change. The bridge validates SHAPE only (exactly 6
booleans) and relays SAP's behaviour — it does not judge whether a DOF pattern is
structurally sensible (anti-pattern #4: SAP itself accepts even all-false), and it does
NOT proactively unlock a locked model.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §21):

  * cAnalyze.SetActiveDOF(Boolean[] DOF) — takes a 6-element .NET Boolean[]; pythonnet
    needs an actual System.Array[Boolean], not a Python list. Returns 0 on success.
  * On a LOCKED model SetActiveDOF returns ret=1 and does NOT apply the change, and does
    NOT auto-unlock. The bridge relays that as oapi_call_failed — it never unlocks for you.
  * Changing active_dof on an unlocked model does not by itself change the lock state.
    The response echoes model_is_locked after the operation as a fact.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import ActiveDOFChange, SetActiveDOFResponse
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.active_dof")

_DOF_COUNT = 6
_DOF_LABELS = ("U1", "U2", "U3", "R1", "R2", "R3")


def _read_active_dof(sap_model: Any) -> list[bool]:
    ret, dof = sap_model.Analyze.GetActiveDOF(None)
    if ret != 0:
        raise SapSessionError(error_codes.OAPI_CALL_FAILED, f"Analyze.GetActiveDOF returned {ret}")
    if dof is None or len(dof) != _DOF_COUNT:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Analyze.GetActiveDOF returned {0 if dof is None else len(dof)} flags, expected {_DOF_COUNT}",
        )
    return [bool(dof[i]) for i in range(_DOF_COUNT)]


def _diff(old: list[bool], new: list[bool]) -> list[str]:
    """Human-readable per-DOF diff, e.g. ['U2: false → true']. Only changed DOFs."""
    return [
        f"{_DOF_LABELS[i]}: {str(old[i]).lower()} → {str(new[i]).lower()}"
        for i in range(_DOF_COUNT)
        if old[i] != new[i]
    ]


def set_active_dof(
    sap_model: Any, oapi_namespace: Any, active_dof: list[bool], dry_run: bool, confirm: bool
) -> SetActiveDOFResponse:
    """Set the model's active DOFs. Shape-validated (exactly 6 booleans), confirm-gated,
    dry-run-capable. Relays SAP's result; never auto-unlocks.

    Raises OAPI_UNEXPECTED_SHAPE for a malformed vector, CONFIRM_REQUIRED if applying
    without confirm, OAPI_CALL_FAILED if SetActiveDOF fails (e.g. a locked model).
    """
    with audited(
        "set_active_dof",
        {"active_dof": active_dof, "dry_run": dry_run, "confirm": confirm},
    ) as ctx:
        # Shape validation — the bridge's responsibility, not domain judgement.
        if not isinstance(active_dof, list) or len(active_dof) != _DOF_COUNT or not all(
            isinstance(b, bool) for b in active_dof
        ):
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"active_dof must be a list of exactly {_DOF_COUNT} booleans "
                f"[U1,U2,U3,R1,R2,R3]; got {active_dof!r}",
            )

        current = _read_active_dof(sap_model)
        changes = _diff(current, active_dof)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"current": current, "new": active_dof, "changes": changes}
            return SetActiveDOFResponse(
                dry_run=True,
                validation_passed=True,
                would_apply=ActiveDOFChange(
                    current_active_dof=current, new_active_dof=active_dof, changes=changes
                ),
                model_is_locked=bool(sap_model.GetModelIsLocked()),
            )

        # Global setting → confirm mandatory (write_side_design.md §5.3).
        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "set_active_dof changes a global model setting (active DOFs); "
                "pass confirm=true to apply",
            )

        import System  # type: ignore

        dof_array = System.Array[System.Boolean](list(active_dof))
        sret = sap_model.Analyze.SetActiveDOF(dof_array)
        # SetActiveDOF returns (ret, dof) via pythonnet; the first element is the status.
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            # e.g. a locked model returns 1 and does not apply. Relay it; do not unlock.
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"Analyze.SetActiveDOF returned {ret_code} (the change was not applied; "
                "a locked model rejects it — unlock in SAP if intended)",
            )

        applied_now = _read_active_dof(sap_model)
        ctx["result_details"] = {
            "previous": current, "current": applied_now, "changes": changes
        }
        return SetActiveDOFResponse(
            dry_run=False,
            applied=ActiveDOFChange(
                previous_active_dof=current, current_active_dof=applied_now, changes=changes
            ),
            model_is_locked=bool(sap_model.GetModelIsLocked()),
        )
