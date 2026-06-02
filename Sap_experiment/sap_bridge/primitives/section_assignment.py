"""Assign sections to frames — the first BATCH write over pre-existing objects (Fase 1g.7).

Two primitives sharing one core: assign_section_to_frames (one section → many frames) and
assign_sections_to_frames (a heterogeneous frame→section mapping). The OAPI has no native
heterogeneous batch (brechas §25), so the bridge composes a loop over cFrameObj.SetSection;
the external API is identical in both cases.

Discipline (write_side_design.md §4, client_patterns #1):
  * STRICT pre-validation: the section(s) and EVERY frame must exist before anything is
    touched. If pre-validation passes, the loop runs. So in normal flow there is NEVER a
    failed_at — it is reserved for an unexpected OAPI failure mid-loop (race/bug), where
    stop-on-first-failure kicks in: applied = frames done, failed_at = the one that broke,
    not_attempted = the rest.
  * confirm is mandatory (the operation modifies pre-existing frames, §5.1).
  * A >10-frame result carries a `hint` suggesting dry_run (decisión #2; suggestion, not
    enforcement).
  * Idempotent assignments (frame already has the target section) are reported as applied
    with previous==current (coherent with set_present_units idempotence), not skipped.

OAPI notes (brechas §25): SetSection(Name, PropName, eItemType.Objects, 0.0, 0.0) → 0 OK;
frame or section not found → ret=1.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    AssignmentPreview,
    AssignmentResponse,
    BatchFailure,
    FrameAssignmentApplied,
    FrameAssignmentPreview,
)
from ..sap_session import SapSessionError
from . import frames as frames_read
from . import sections as sections_read

logger = logging.getLogger("sap_bridge.primitives.section_assignment")

_HINT_THRESHOLD = 10


def _hint_for(frame_count: int) -> str | None:
    if frame_count > _HINT_THRESHOLD:
        return (f"This operation affects {frame_count} frames. "
                "Consider dry_run=true first to verify the list.")
    return None


def _validate_sections_exist(sap_model: Any, oapi_namespace: Any, section_names: set[str]) -> None:
    existing = set(sections_read.list_section_names(sap_model, oapi_namespace))
    missing = sorted(s for s in section_names if s not in existing)
    if missing:
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"section(s) not found: {missing} (list with GET /v1/sections)",
        )


def _validate_frames_exist(sap_model: Any, frame_names: list[str]) -> None:
    existing = set(frames_read.list_frame_names(sap_model))
    missing = sorted({f for f in frame_names if f not in existing})
    if missing:
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"frame(s) not found: {missing} (list with GET /v1/frames)",
        )


def _apply_loop(
    sap_model: Any, oapi_namespace: Any, pairs: list[tuple[str, str]]
) -> tuple[list[FrameAssignmentApplied], BatchFailure | None, list[str]]:
    """Loop SetSection over (frame, section) pairs. Stop-on-first-failure.

    Returns (applied, failed_at, not_attempted). In normal flow failed_at is None — strict
    pre-validation already guaranteed everything exists; this guards against a mid-loop
    OAPI surprise.
    """
    obj_item = oapi_namespace.eItemType.Objects
    applied: list[FrameAssignmentApplied] = []
    for idx, (frame_name, section_name) in enumerate(pairs):
        previous = frames_read.get_frame_section(sap_model, frame_name)
        ret = sap_model.FrameObj.SetSection(frame_name, section_name, obj_item, 0.0, 0.0)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            failed = BatchFailure(
                frame=frame_name,
                reason=f"FrameObj.SetSection returned {ret_code} (unexpected after "
                       "pre-validation — possible race or OAPI issue)",
            )
            not_attempted = [p[0] for p in pairs[idx + 1:]]
            return applied, failed, not_attempted
        current = frames_read.get_frame_section(sap_model, frame_name)  # read back (M2)
        applied.append(FrameAssignmentApplied(
            frame=frame_name, previous_section=previous, current_section=current
        ))
    return applied, None, []


def _run_batch(
    sap_model: Any, oapi_namespace: Any, operation: str, pairs: list[tuple[str, str]],
    dry_run: bool, confirm: bool, audit_params: dict
) -> AssignmentResponse:
    """Shared core for both assign primitives. ``pairs`` is the resolved frame→section list;
    sections + frames are validated here before any write."""
    with audited(operation, audit_params) as ctx:
        if not pairs:
            raise SapSessionError(
                error_codes.EMPTY_BATCH, f"{operation}: the batch is empty",
            )

        # Strict pre-validation: every referenced section and frame must exist.
        _validate_sections_exist(sap_model, oapi_namespace, {sec for _f, sec in pairs})
        _validate_frames_exist(sap_model, [f for f, _sec in pairs])

        frame_count = len(pairs)
        hint = _hint_for(frame_count)

        if dry_run:
            previews: list[FrameAssignmentPreview] = []
            changes: list[str] = []
            for frame_name, section_name in pairs:
                cur = frames_read.get_frame_section(sap_model, frame_name)
                previews.append(FrameAssignmentPreview(
                    frame=frame_name, current_section=cur, new_section=section_name
                ))
                if cur != section_name:
                    changes.append(f"{frame_name}: {cur} → {section_name}")
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"frame_count": frame_count, "change_count": len(changes)}
            return AssignmentResponse(
                dry_run=True, operation=operation, validation_passed=True,
                would_apply=AssignmentPreview(
                    frame_count=frame_count, current_assignments=previews, changes=changes
                ),
                hint=hint,
            )

        # Mutating pre-existing frames → confirm mandatory (§5.1).
        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"{operation} modifies {frame_count} pre-existing frame(s); "
                "pass confirm=true to apply",
            )

        applied, failed_at, not_attempted = _apply_loop(sap_model, oapi_namespace, pairs)
        ctx["result"] = "applied" if failed_at is None else f"error_{error_codes.OAPI_CALL_FAILED}"
        ctx["result_details"] = {
            "applied_count": len(applied),
            "failed_at": failed_at.frame if failed_at else None,
        }
        return AssignmentResponse(
            dry_run=False, operation=operation, applied=applied,
            failed_at=failed_at, not_attempted=not_attempted, hint=hint,
        )


def assign_section_to_frames(
    sap_model: Any, oapi_namespace: Any, section_name: str, frame_names: list[str],
    dry_run: bool, confirm: bool
) -> AssignmentResponse:
    """Assign ONE section to many frames (homogeneous batch)."""
    pairs = [(f, section_name) for f in frame_names]
    return _run_batch(
        sap_model, oapi_namespace, "assign_section_to_frames", pairs, dry_run, confirm,
        {"section_name": section_name, "frame_names": frame_names,
         "dry_run": dry_run, "confirm": confirm},
    )


def assign_sections_to_frames(
    sap_model: Any, oapi_namespace: Any, assignments: list[dict], dry_run: bool, confirm: bool
) -> AssignmentResponse:
    """Assign sections to frames per a heterogeneous frame→section mapping."""
    pairs = [(a["frame_name"], a["section_name"]) for a in assignments]
    return _run_batch(
        sap_model, oapi_namespace, "assign_sections_to_frames", pairs, dry_run, confirm,
        {"assignments": assignments, "dry_run": dry_run, "confirm": confirm},
    )
