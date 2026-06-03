"""Read point loads (force + moment) on ONE joint across all patterns, from the model.

Pure facts: each load's pattern, coordinate system and six force/moment components. The
bridge does not resolve the coordinate system or name directions. A joint with no point
loads returns an empty list (not an error).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §11):

  * cPointObj.GetLoadForce(Name, ref NumberItems, ref PointName[], ref LoadPat[],
    ref LcStep[], ref CSys[], ref F1[], ref F2[], ref F3[], ref M1[], ref M2[], ref M3[],
    eItemType) — the six components come back as SIX separate flat arrays (F1..M3), NOT
    a 2D array. We pass eItemType.Objects to scope to this one joint.
  * TEST_01 has no point loads on any joint (0/112), so this primitive is validated on
    the empty path; non-empty coverage waits for a model that carries joint loads.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    AssignJointLoadResponse,
    AssignJointLoadsBatchResponse,
    BatchItemFailure,
    ClearJointLoadsResponse,
    ClearJointLoadsResult,
    JointForces,
    JointLoad,
    JointLoadApplied,
    JointLoadsResponse,
    JointMoments,
    PointLoad,
)
from ..sap_session import SapSessionError
from . import joints as joints_read
from . import load_patterns as load_patterns_read
from .helpers import apply_batch_atomic

logger = logging.getLogger("sap_bridge.primitives.joint_loads")


def get_point_loads_on_joint(sap_model: Any, oapi_namespace: Any, joint_name: str) -> list[PointLoad]:
    """Return every point load on ``joint_name``, across all patterns.

    Empty list if the joint carries no point loads. Raises
    SapSessionError(OAPI_CALL_FAILED) on a non-zero OAPI return (e.g. unknown joint),
    and OAPI_UNEXPECTED_SHAPE if the parallel arrays are missing/short for the count.
    """
    point = sap_model.PointObj
    obj_item = oapi_namespace.eItemType.Objects

    ret, nitems, _pnames, load_pats, _lcstep, csyses, f1, f2, f3, m1, m2, m3 = (
        point.GetLoadForce(
            joint_name, 0, None, None, None, None, None, None, None, None, None, None, obj_item
        )
    )
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.GetLoadForce('{joint_name}') returned {ret} "
            "(unknown joint? cross-check /v1/joints)",
        )
    if nitems == 0:
        return []

    arrays = (load_pats, csyses, f1, f2, f3, m1, m2, m3)
    if any(a is None or len(a) < nitems for a in arrays):
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"PointObj.GetLoadForce('{joint_name}') reported {nitems} items but a "
            "parallel array is missing or shorter",
        )

    loads: list[PointLoad] = []
    for i in range(nitems):
        loads.append(
            PointLoad(
                load_pattern=str(load_pats[i]),
                coord_system=str(csyses[i]),
                f1=float(f1[i]),
                f2=float(f2[i]),
                f3=float(f3[i]),
                m1=float(m1[i]),
                m2=float(m2[i]),
                m3=float(m3[i]),
            )
        )
    return loads


# --- Write-side: assign / clear / get (Fase 1h.4) ----------------------------
# Assignment ACCUMULATES (Replace=False, decisión #5). Order [F1,F2,F3,M1,M2,M3] (§36).


def _objects_item(sap_model: Any) -> Any:
    from ..sap_session import get_session
    return get_session().oapi_namespace().eItemType.Objects


def _value_array(forces: dict, moments: dict) -> list[float]:
    f = JointForces(**(forces or {}))
    m = JointMoments(**(moments or {}))
    return [f.F1, f.F2, f.F3, m.M1, m.M2, m.M3]


def _validate_joint(sap_model: Any, name: str) -> None:
    if name not in set(joints_read.list_joint_names(sap_model)):
        raise SapSessionError(error_codes.OBJECT_NOT_FOUND, f"joint '{name}' not found")


def _read_joint_loads(sap_model: Any, joint_name: str) -> list[JointLoad]:
    """Unpack GetLoadForce into JointLoad records (the new named shape)."""
    g = sap_model.PointObj.GetLoadForce(
        joint_name, 0, None, None, None, None, None, None, None, None, None, None,
        _objects_item(sap_model),
    )
    if g[0] != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"PointObj.GetLoadForce('{joint_name}') returned {g[0]}"
        )
    n = g[1]
    if not n:
        return []
    load_pat, csys = list(g[3]), list(g[5])
    f1, f2, f3, m1, m2, m3 = (list(g[k]) for k in (6, 7, 8, 9, 10, 11))
    return [
        JointLoad(
            pattern_name=str(load_pat[i]),
            forces=JointForces(F1=float(f1[i]), F2=float(f2[i]), F3=float(f3[i])),
            moments=JointMoments(M1=float(m1[i]), M2=float(m2[i]), M3=float(m3[i])),
            coord_sys=str(csys[i]),
        )
        for i in range(n)
    ]


def _do_assign(sap_model: Any, joint_name: str, pattern_name: str, forces: dict, moments: dict,
               coord_sys: str) -> None:
    ret = sap_model.PointObj.SetLoadForce(
        joint_name, pattern_name, _value_array(forces, moments), False, coord_sys,
        _objects_item(sap_model),
    )
    ret_code = ret[0] if isinstance(ret, tuple) else ret
    if ret_code != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.SetLoadForce('{joint_name}', '{pattern_name}') returned {ret_code}",
        )


def _record(joint_name: str, pattern_name: str, forces: dict, moments: dict,
            coord_sys: str) -> JointLoadApplied:
    return JointLoadApplied(
        joint_name=joint_name,
        load=JointLoad(pattern_name=pattern_name, forces=JointForces(**(forces or {})),
                       moments=JointMoments(**(moments or {})), coord_sys=coord_sys),
        note="accumulated (added to existing load for this pattern)",
    )


def assign_joint_load(
    sap_model: Any, joint_name: str, pattern_name: str, forces: dict, moments: dict,
    coord_sys: str, dry_run: bool, confirm: bool,
) -> AssignJointLoadResponse:
    """Assign a point load to a joint (accumulates). Validates joint + pattern exist."""
    with audited("assign_joint_load", {"joint_name": joint_name, "pattern_name": pattern_name,
                                       "forces": forces, "moments": moments, "coord_sys": coord_sys,
                                       "dry_run": dry_run, "confirm": confirm}) as ctx:
        _validate_joint(sap_model, joint_name)
        load_patterns_read.validate_load_pattern_exists(sap_model, pattern_name)
        record = _record(joint_name, pattern_name, forces, moments, coord_sys)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"joint_name": joint_name, "pattern_name": pattern_name}
            return AssignJointLoadResponse(dry_run=True, would_apply=record)

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "assign_joint_load modifies the model; pass confirm=true to apply",
            )

        _do_assign(sap_model, joint_name, pattern_name, forces, moments, coord_sys)
        ctx["result_details"] = {"joint_name": joint_name, "pattern_name": pattern_name}
        return AssignJointLoadResponse(dry_run=False, applied=record)


def assign_joint_loads_batch(
    sap_model: Any, items: list[dict], dry_run: bool, confirm: bool,
) -> AssignJointLoadsBatchResponse:
    """Assign point loads to many joints atomically (stop-on-first-failure)."""
    with audited("assign_joint_loads_batch",
                 {"count": len(items), "dry_run": dry_run, "confirm": confirm}) as ctx:
        if not items:
            raise SapSessionError(error_codes.EMPTY_BATCH, "assign_joint_loads_batch: empty")

        records: list[tuple[dict, JointLoadApplied]] = []
        for spec in items:
            _validate_joint(sap_model, spec["joint_name"])
            load_patterns_read.validate_load_pattern_exists(sap_model, spec["pattern_name"])
            records.append((spec, _record(
                spec["joint_name"], spec["pattern_name"], spec.get("forces", {}),
                spec.get("moments", {}), spec.get("coord_sys", "Global"))))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"count": len(records)}
            return AssignJointLoadsBatchResponse(
                dry_run=True, count=len(records), would_apply=[r for _s, r in records])

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"assign_joint_loads_batch modifies {len(items)} joint(s); pass confirm=true",
            )

        def _apply(_idx: int, item: tuple[dict, JointLoadApplied]) -> JointLoadApplied:
            spec, rec = item
            _do_assign(sap_model, spec["joint_name"], spec["pattern_name"],
                       spec.get("forces", {}), spec.get("moments", {}), spec.get("coord_sys", "Global"))
            return rec

        outcome = apply_batch_atomic(records, _apply)
        failed, not_attempted = None, None
        if outcome.failed_index is not None:
            _s, rec = outcome.failed_item
            failed = BatchItemFailure(index=outcome.failed_index,
                                      item=f"joint '{rec.joint_name}' / pattern '{rec.load.pattern_name}'",
                                      reason=outcome.failed_reason or "unknown")
            not_attempted = [r.joint_name for _s2, r in outcome.not_attempted]
        ctx["result"] = "applied" if failed is None else f"error_{error_codes.OAPI_CALL_FAILED}"
        ctx["result_details"] = {"applied_count": len(outcome.applied)}
        return AssignJointLoadsBatchResponse(
            dry_run=False, count=len(records), applied=outcome.applied,
            failed_at=failed, not_attempted=not_attempted)


def clear_joint_loads(
    sap_model: Any, joint_name: str, pattern_name: str | None, dry_run: bool, confirm: bool,
) -> ClearJointLoadsResponse:
    """Clear loads on a joint. pattern_name given → only that pattern; None → ALL. DeleteLoadForce
    actually clears (≠ §34)."""
    with audited("clear_joint_loads", {"joint_name": joint_name, "pattern_name": pattern_name,
                                       "dry_run": dry_run, "confirm": confirm}) as ctx:
        _validate_joint(sap_model, joint_name)
        existing = _read_joint_loads(sap_model, joint_name)
        targets = [ld for ld in existing if pattern_name is None or ld.pattern_name == pattern_name]
        result = ClearJointLoadsResult(
            joint_name=joint_name, pattern_name=pattern_name, cleared_count=len(targets))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"joint_name": joint_name, "cleared_count": len(targets)}
            return ClearJointLoadsResponse(dry_run=True, would_apply=result)

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "clear_joint_loads removes loads; pass confirm=true to clear",
            )

        item = _objects_item(sap_model)
        patterns = [pattern_name] if pattern_name is not None else sorted(
            {ld.pattern_name for ld in existing})
        for pat in patterns:
            ret = sap_model.PointObj.DeleteLoadForce(joint_name, pat, item)
            ret_code = ret[0] if isinstance(ret, tuple) else ret
            if ret_code != 0:
                raise SapSessionError(
                    error_codes.OAPI_CALL_FAILED,
                    f"PointObj.DeleteLoadForce('{joint_name}', '{pat}') returned {ret_code}",
                )
        ctx["result_details"] = {"joint_name": joint_name, "cleared_count": len(targets)}
        return ClearJointLoadsResponse(dry_run=False, applied=result)


def get_joint_loads(sap_model: Any, joint_name: str) -> JointLoadsResponse:
    """Read all loads on one joint (read-only), one entry per pattern (named-shape)."""
    _validate_joint(sap_model, joint_name)
    loads = _read_joint_loads(sap_model, joint_name)
    return JointLoadsResponse(joint_name=joint_name, count=len(loads), loads=loads)
