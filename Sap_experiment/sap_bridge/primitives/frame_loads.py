"""Read distributed loads on ONE frame across all load patterns, from the live model.

Pure facts: each load's pattern, type, direction, coordinate system, relative extents
and values. The bridge relays the direction as SAP's raw code plus its documented name —
it never interprets 'Gravity' as 'down' or resolves a custom coordinate system (brief,
Principle 1). A frame with no distributed loads returns an empty list (not an error).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §11):

  * cFrameObj.GetLoadDistributed(Name, ref NumberItems, ref FrameName[], ref LoadPat[],
    ref MyType[], ref CSys[], ref Dir[], ref RD1[], ref RD2[], ref Dist1[], ref Dist2[],
    ref Val1[], ref Val2[], eItemType) — 11 PARALLEL arrays after the count. We pass
    eItemType.Objects to scope to this one frame. None is accepted as array placeholder.
  * Dir is a raw INTEGER (no direction enum in this assembly, same situation as
    combo_type §10). MyType is 1=Force, 2=Displacement. We map both to documented names
    and also surface the raw code.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    AssignFrameLoadDistributedResponse,
    AssignFrameLoadPointResponse,
    AssignFrameLoadsDistributedBatchResponse,
    AssignFrameLoadsPointBatchResponse,
    BatchItemFailure,
    DistributedLoad,
    FrameDistributedLoad,
    FrameDistributedLoadApplied,
    FramePointLoad,
    FramePointLoadApplied,
)
from ..sap_session import SapSessionError
from . import frames as frames_read
from . import load_patterns as load_patterns_read
from .helpers import apply_batch_atomic, resolve_load_direction, resolve_load_type

logger = logging.getLogger("sap_bridge.primitives.frame_loads")

# SAP2000 OAPI documented Dir integer mapping for frame distributed loads. The assembly
# returns a bare int; the bridge maps it to SAP's own name (a relay, not domain
# interpretation), surfacing 'Unknown' for an out-of-range code rather than guessing.
_DIRECTION_NAMES = {
    1: "Local 1",
    2: "Local 2",
    3: "Local 3",
    4: "Global X",
    5: "Global Y",
    6: "Global Z",
    7: "Projected X",
    8: "Projected Y",
    9: "Projected Z",
    10: "Gravity",
    11: "Projected Gravity",
}

# MyType integer mapping (1=Force, 2=Displacement).
_LOAD_TYPE_NAMES = {1: "Force", 2: "Displacement"}


def get_distributed_loads_on_frame(sap_model: Any, oapi_namespace: Any, frame_name: str) -> list[DistributedLoad]:
    """Return every distributed load on ``frame_name``, across all patterns.

    Empty list if the frame carries no distributed loads. Raises
    SapSessionError(OAPI_CALL_FAILED) on a non-zero OAPI return (e.g. unknown frame),
    and OAPI_UNEXPECTED_SHAPE if the parallel arrays are missing/short for the count.
    """
    frame = sap_model.FrameObj
    obj_item = oapi_namespace.eItemType.Objects

    ret, nitems, _fnames, load_pats, my_types, csyses, dirs, rd1, rd2, _d1, _d2, val1, val2 = (
        frame.GetLoadDistributed(
            frame_name, 0, None, None, None, None, None, None, None, None, None, None, None, obj_item
        )
    )
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.GetLoadDistributed('{frame_name}') returned {ret} "
            "(unknown frame? cross-check /v1/frames)",
        )
    if nitems == 0:
        return []

    arrays = (load_pats, my_types, csyses, dirs, rd1, rd2, val1, val2)
    if any(a is None or len(a) < nitems for a in arrays):
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"FrameObj.GetLoadDistributed('{frame_name}') reported {nitems} items but a "
            "parallel array is missing or shorter",
        )

    loads: list[DistributedLoad] = []
    for i in range(nitems):
        dir_code = int(dirs[i])
        type_code = int(my_types[i])
        loads.append(
            DistributedLoad(
                load_pattern=str(load_pats[i]),
                load_type=_LOAD_TYPE_NAMES.get(type_code, "Unknown"),
                direction=_DIRECTION_NAMES.get(dir_code, "Unknown"),
                direction_code=dir_code,
                coord_system=str(csyses[i]),
                rel_dist_start=float(rd1[i]),
                rel_dist_end=float(rd2[i]),
                value_start=float(val1[i]),
                value_end=float(val2[i]),
            )
        )
    return loads


# --- Write-side: distributed loads (Fase 1h.4) -------------------------------
# Uniform load (Val1=Val2 over 0%-100% of the frame). Accumulates (Replace=False, decisión #5).
# direction string → (Dir, CSys) via the §35 helper.


def _objects_item(sap_model: Any) -> Any:
    from ..sap_session import get_session
    return get_session().oapi_namespace().eItemType.Objects


def _validate_frame(sap_model: Any, name: str) -> None:
    if name not in set(frames_read.list_frame_names(sap_model)):
        raise SapSessionError(error_codes.OBJECT_NOT_FOUND, f"frame '{name}' not found")


def _do_assign_distributed(sap_model: Any, frame_name: str, pattern_name: str, value: float,
                           direction: str, coord_sys: str, load_type: str) -> tuple[int, str]:
    """SetLoadDistributed uniform over 0..1. Returns the resolved (dir_code, csys) for reporting."""
    dir_code, csys = resolve_load_direction(direction, coord_sys)
    my_type = resolve_load_type(load_type)
    ret = sap_model.FrameObj.SetLoadDistributed(
        frame_name, pattern_name, my_type, dir_code, 0.0, 1.0, value, value, csys, True, False,
        _objects_item(sap_model),
    )
    ret_code = ret[0] if isinstance(ret, tuple) else ret
    if ret_code != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.SetLoadDistributed('{frame_name}', '{pattern_name}') returned {ret_code}",
        )
    return dir_code, csys


def _distributed_record(frame_name: str, pattern_name: str, value: float, direction: str,
                        dir_code: int, csys: str, load_type: str) -> FrameDistributedLoadApplied:
    return FrameDistributedLoadApplied(
        frame_name=frame_name,
        load=FrameDistributedLoad(
            pattern_name=pattern_name, load_type=load_type, direction=direction, dir_code=dir_code,
            coord_sys=csys, rel_dist1=0.0, rel_dist2=1.0, value1=value, value2=value),
    )


def assign_frame_load_distributed(
    sap_model: Any, frame_name: str, pattern_name: str, value: float, direction: str,
    coord_sys: str, load_type: str, dry_run: bool, confirm: bool,
) -> AssignFrameLoadDistributedResponse:
    """Assign a uniform distributed load to a frame (accumulates). Validates frame + pattern."""
    with audited("assign_frame_load_distributed",
                 {"frame_name": frame_name, "pattern_name": pattern_name, "value": value,
                  "direction": direction, "coord_sys": coord_sys, "load_type": load_type,
                  "dry_run": dry_run, "confirm": confirm}) as ctx:
        _validate_frame(sap_model, frame_name)
        load_patterns_read.validate_load_pattern_exists(sap_model, pattern_name)
        # Resolve direction now so a bad name fails before confirm (and the preview is accurate).
        dir_code, csys = resolve_load_direction(direction, coord_sys)
        resolve_load_type(load_type)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"frame_name": frame_name, "dir_code": dir_code}
            return AssignFrameLoadDistributedResponse(
                dry_run=True,
                would_apply=_distributed_record(frame_name, pattern_name, value, direction,
                                                dir_code, csys, load_type))

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "assign_frame_load_distributed modifies the model; pass confirm=true to apply",
            )

        dir_code, csys = _do_assign_distributed(sap_model, frame_name, pattern_name, value,
                                                direction, coord_sys, load_type)
        ctx["result_details"] = {"frame_name": frame_name, "dir_code": dir_code}
        return AssignFrameLoadDistributedResponse(
            dry_run=False,
            applied=_distributed_record(frame_name, pattern_name, value, direction, dir_code,
                                        csys, load_type))


def assign_frame_load_distributed_batch(
    sap_model: Any, items: list[dict], dry_run: bool, confirm: bool,
) -> AssignFrameLoadsDistributedBatchResponse:
    """Assign uniform distributed loads to many frames atomically (stop-on-first-failure)."""
    with audited("assign_frame_load_distributed_batch",
                 {"count": len(items), "dry_run": dry_run, "confirm": confirm}) as ctx:
        if not items:
            raise SapSessionError(error_codes.EMPTY_BATCH, "assign_frame_load_distributed_batch: empty")

        records: list[tuple[dict, FrameDistributedLoadApplied]] = []
        for spec in items:
            _validate_frame(sap_model, spec["frame_name"])
            load_patterns_read.validate_load_pattern_exists(sap_model, spec["pattern_name"])
            cs = spec.get("coord_sys", "Global")
            lt = spec.get("load_type", "Force")
            dir_code, csys = resolve_load_direction(spec["direction"], cs)
            resolve_load_type(lt)
            records.append((spec, _distributed_record(
                spec["frame_name"], spec["pattern_name"], spec["value"], spec["direction"],
                dir_code, csys, lt)))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"count": len(records)}
            return AssignFrameLoadsDistributedBatchResponse(
                dry_run=True, count=len(records), would_apply=[r for _s, r in records])

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"assign_frame_load_distributed_batch modifies {len(items)} frame(s); pass confirm=true",
            )

        def _apply(_idx: int, item: tuple[dict, FrameDistributedLoadApplied]) -> FrameDistributedLoadApplied:
            spec, rec = item
            _do_assign_distributed(sap_model, spec["frame_name"], spec["pattern_name"],
                                   spec["value"], spec["direction"], spec.get("coord_sys", "Global"),
                                   spec.get("load_type", "Force"))
            return rec

        outcome = apply_batch_atomic(records, _apply)
        failed, not_attempted = None, None
        if outcome.failed_index is not None:
            _s, rec = outcome.failed_item
            failed = BatchItemFailure(index=outcome.failed_index,
                                      item=f"frame '{rec.frame_name}' / pattern '{rec.load.pattern_name}'",
                                      reason=outcome.failed_reason or "unknown")
            not_attempted = [r.frame_name for _s2, r in outcome.not_attempted]
        ctx["result"] = "applied" if failed is None else f"error_{error_codes.OAPI_CALL_FAILED}"
        ctx["result_details"] = {"applied_count": len(outcome.applied)}
        return AssignFrameLoadsDistributedBatchResponse(
            dry_run=False, count=len(records), applied=outcome.applied,
            failed_at=failed, not_attempted=not_attempted)


# --- Write-side: point loads (Fase 1h.4) -------------------------------------


def _do_assign_point(sap_model: Any, frame_name: str, pattern_name: str, value: float,
                     distance: float, direction: str, rel_distance: bool, coord_sys: str,
                     load_type: str) -> tuple[int, str]:
    dir_code, csys = resolve_load_direction(direction, coord_sys)
    my_type = resolve_load_type(load_type)
    ret = sap_model.FrameObj.SetLoadPoint(
        frame_name, pattern_name, my_type, dir_code, distance, value, csys, rel_distance, False,
        _objects_item(sap_model),
    )
    ret_code = ret[0] if isinstance(ret, tuple) else ret
    if ret_code != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.SetLoadPoint('{frame_name}', '{pattern_name}') returned {ret_code}",
        )
    return dir_code, csys


def _point_record(frame_name: str, pattern_name: str, value: float, distance: float,
                  direction: str, dir_code: int, rel_distance: bool, csys: str,
                  load_type: str) -> FramePointLoadApplied:
    return FramePointLoadApplied(
        frame_name=frame_name,
        load=FramePointLoad(
            pattern_name=pattern_name, load_type=load_type, direction=direction, dir_code=dir_code,
            coord_sys=csys, rel_distance=rel_distance, distance=distance, value=value),
    )


def assign_frame_load_point(
    sap_model: Any, frame_name: str, pattern_name: str, value: float, distance: float,
    direction: str, rel_distance: bool, coord_sys: str, load_type: str, dry_run: bool, confirm: bool,
) -> AssignFrameLoadPointResponse:
    """Assign a point load to a frame at ``distance`` (accumulates). Validates frame + pattern."""
    with audited("assign_frame_load_point",
                 {"frame_name": frame_name, "pattern_name": pattern_name, "value": value,
                  "distance": distance, "direction": direction, "rel_distance": rel_distance,
                  "coord_sys": coord_sys, "load_type": load_type,
                  "dry_run": dry_run, "confirm": confirm}) as ctx:
        _validate_frame(sap_model, frame_name)
        load_patterns_read.validate_load_pattern_exists(sap_model, pattern_name)
        dir_code, csys = resolve_load_direction(direction, coord_sys)
        resolve_load_type(load_type)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"frame_name": frame_name, "dir_code": dir_code}
            return AssignFrameLoadPointResponse(
                dry_run=True,
                would_apply=_point_record(frame_name, pattern_name, value, distance, direction,
                                          dir_code, rel_distance, csys, load_type))

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "assign_frame_load_point modifies the model; pass confirm=true to apply",
            )

        dir_code, csys = _do_assign_point(sap_model, frame_name, pattern_name, value, distance,
                                          direction, rel_distance, coord_sys, load_type)
        ctx["result_details"] = {"frame_name": frame_name, "dir_code": dir_code}
        return AssignFrameLoadPointResponse(
            dry_run=False,
            applied=_point_record(frame_name, pattern_name, value, distance, direction, dir_code,
                                  rel_distance, csys, load_type))


def assign_frame_load_point_batch(
    sap_model: Any, items: list[dict], dry_run: bool, confirm: bool,
) -> AssignFrameLoadsPointBatchResponse:
    """Assign point loads to many frames atomically (stop-on-first-failure)."""
    with audited("assign_frame_load_point_batch",
                 {"count": len(items), "dry_run": dry_run, "confirm": confirm}) as ctx:
        if not items:
            raise SapSessionError(error_codes.EMPTY_BATCH, "assign_frame_load_point_batch: empty")

        records: list[tuple[dict, FramePointLoadApplied]] = []
        for spec in items:
            _validate_frame(sap_model, spec["frame_name"])
            load_patterns_read.validate_load_pattern_exists(sap_model, spec["pattern_name"])
            cs = spec.get("coord_sys", "Global")
            lt = spec.get("load_type", "Force")
            rd = spec.get("rel_distance", True)
            dir_code, csys = resolve_load_direction(spec["direction"], cs)
            resolve_load_type(lt)
            records.append((spec, _point_record(
                spec["frame_name"], spec["pattern_name"], spec["value"], spec["distance"],
                spec["direction"], dir_code, rd, csys, lt)))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"count": len(records)}
            return AssignFrameLoadsPointBatchResponse(
                dry_run=True, count=len(records), would_apply=[r for _s, r in records])

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"assign_frame_load_point_batch modifies {len(items)} frame(s); pass confirm=true",
            )

        def _apply(_idx: int, item: tuple[dict, FramePointLoadApplied]) -> FramePointLoadApplied:
            spec, rec = item
            _do_assign_point(sap_model, spec["frame_name"], spec["pattern_name"], spec["value"],
                             spec["distance"], spec["direction"], spec.get("rel_distance", True),
                             spec.get("coord_sys", "Global"), spec.get("load_type", "Force"))
            return rec

        outcome = apply_batch_atomic(records, _apply)
        failed, not_attempted = None, None
        if outcome.failed_index is not None:
            _s, rec = outcome.failed_item
            failed = BatchItemFailure(index=outcome.failed_index,
                                      item=f"frame '{rec.frame_name}' / pattern '{rec.load.pattern_name}'",
                                      reason=outcome.failed_reason or "unknown")
            not_attempted = [r.frame_name for _s2, r in outcome.not_attempted]
        ctx["result"] = "applied" if failed is None else f"error_{error_codes.OAPI_CALL_FAILED}"
        ctx["result_details"] = {"applied_count": len(outcome.applied)}
        return AssignFrameLoadsPointBatchResponse(
            dry_run=False, count=len(records), applied=outcome.applied,
            failed_at=failed, not_attempted=not_attempted)
