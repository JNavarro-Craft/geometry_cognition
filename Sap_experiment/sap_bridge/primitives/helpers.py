"""Shared write-side helpers for geometry primitives (Fase 1h.2).

Three reusable building blocks, designed future-aware so 1h.3 (restraints) and 1h.4 (loads)
inherit them instead of re-deriving:

  * ``apply_batch_atomic`` — the stop-on-first-failure batch engine, generalized from the
    section-assignment loop of 1g.7. Any batch primitive (create_joints/frames now,
    set restraints/loads later) feeds it items + an apply function and gets back the
    canonical {applied, failed_at, not_attempted} triple.
  * ``get_frames_connected_to_joint`` — connection detection for safe deletes. Today it
    answers "which frames touch this joint"; it is the first concrete case of a more general
    "what references object X" pattern (areas/links/restraints/loads will extend it).
  * ``validate_joint_exists`` — a cheap existence check reused by create_frame and modify_*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .. import error_codes
from ..sap_session import SapSessionError
from . import frames as frames_read
from . import joints as joints_read


@dataclass
class BatchOutcome:
    """The canonical result of an atomic batch: what got applied, where it broke (if at all),
    and what was therefore skipped. ``failed_at`` is None in the normal flow (strict
    pre-validation by the caller); it carries (index, item, reason) only on a mid-loop
    surprise, with stop-on-first-failure (decisión #4)."""

    applied: list[Any]
    failed_index: int | None
    failed_item: Any | None
    failed_reason: str | None
    not_attempted: list[Any]


def apply_batch_atomic(items: list[Any], apply_fn: Callable[[int, Any], Any]) -> BatchOutcome:
    """Run ``apply_fn(index, item)`` over ``items``, stopping at the first failure.

    ``apply_fn`` returns an "applied" record on success, or raises SapSessionError to signal a
    mid-loop failure. On the first raise: that item is the failure point, everything after it
    is not_attempted (NOT reverted — the bridge has no transactional undo; the client uses a
    savepoint, client_patterns #2). The caller is expected to have pre-validated, so a failure
    here is the unexpected-OAPI-surprise case, mirrored on assign_sections_to_frames (§25).
    """
    applied: list[Any] = []
    for idx, item in enumerate(items):
        try:
            applied.append(apply_fn(idx, item))
        except SapSessionError as exc:
            return BatchOutcome(
                applied=applied,
                failed_index=idx,
                failed_item=item,
                failed_reason=exc.message,
                not_attempted=items[idx + 1:],
            )
    return BatchOutcome(applied=applied, failed_index=None, failed_item=None,
                        failed_reason=None, not_attempted=[])


def get_frames_connected_to_joint(sap_model: Any, joint_name: str) -> list[str]:
    """Names of every frame whose i or j end point is ``joint_name``.

    Iterates the frame inventory (GetNameList) and reads each frame's endpoints (GetPoints).
    Used by delete_joint to refuse deleting a joint that still has frames. This is the first
    concrete instance of a general "references to object X" query — a future
    get_objects_connected_to_joint would extend it to areas/links/loads. Kept frame-specific
    and explicit here (no premature abstraction) but named so the generalization is obvious.
    """
    connected: list[str] = []
    for fname in frames_read.list_frame_names(sap_model):
        pret, p_i, p_j = sap_model.FrameObj.GetPoints(fname, "", "")
        if pret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"FrameObj.GetPoints('{fname}') returned {pret}",
            )
        if str(p_i) == joint_name or str(p_j) == joint_name:
            connected.append(fname)
    return connected


def validate_joint_exists(sap_model: Any, name: str) -> None:
    """Raise OBJECT_NOT_FOUND if no joint named ``name`` exists. Reused by create_frame
    (both endpoints) and modify_frame (new endpoints)."""
    if name not in set(joints_read.list_joint_names(sap_model)):
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"joint '{name}' not found (list with GET /v1/joints)",
        )


# --- Frame-load direction mapping (Fase 1h.4, §35) ---------------------------
# The OAPI `Dir` is a raw Int32, NOT a named enum, and it is COUPLED to CSys: local axes (1-3)
# require CSys="Local" (with "Global" SAP returns ret=1). Verified code-by-code in pre-flight.
# This helper maps the client's direction string → (Dir, CSys), forcing Local for local axes.
# A future trapezoidal-load primitive reuses it (same Dir/CSys semantics).

# direction name → (Dir code, forced CSys or None to use the caller's coord_sys)
_DIRECTION_MAP: dict[str, tuple[int, str | None]] = {
    "Local1": (1, "Local"), "Local2": (2, "Local"), "Local3": (3, "Local"),
    "X": (4, None), "Y": (5, None), "Z": (6, None),
    "XProj": (7, "Global"), "YProj": (8, "Global"), "ZProj": (9, "Global"),
    "Gravity": (10, "Global"), "GravityProj": (11, "Global"),
}


def load_direction_names() -> list[str]:
    """The accepted frame-load direction names."""
    return list(_DIRECTION_MAP.keys())


def resolve_load_direction(direction: str, coord_sys: str) -> tuple[int, str]:
    """Map a direction string + requested coord_sys to the OAPI ``(Dir, CSys)`` pair (§35).

    Case-insensitive on the direction name. For local axes the CSys is FORCED to 'Local' (SAP
    rejects them otherwise); for projected/gravity it is forced to the system SAP expects; for
    X/Y/Z the caller's coord_sys is used. Raises UNKNOWN_LOAD_DIRECTION for an unmapped name.
    """
    match = next((k for k in _DIRECTION_MAP if k.lower() == direction.lower()), None)
    if match is None:
        raise SapSessionError(
            error_codes.UNKNOWN_LOAD_DIRECTION,
            f"unknown load direction '{direction}'; supported: {', '.join(_DIRECTION_MAP)}",
        )
    dir_code, forced_csys = _DIRECTION_MAP[match]
    return dir_code, (forced_csys if forced_csys is not None else coord_sys)


def resolve_load_type(load_type: str) -> int:
    """Map 'Force'/'Moment' (case-insensitive) to the OAPI MyType (1/2). §36."""
    table = {"force": 1, "moment": 2}
    code = table.get(load_type.lower())
    if code is None:
        raise SapSessionError(
            error_codes.UNKNOWN_LOAD_DIRECTION,  # reuse: a bad load_type is the same client-fix class
            f"unknown load type '{load_type}'; supported: Force, Moment",
        )
    return code
