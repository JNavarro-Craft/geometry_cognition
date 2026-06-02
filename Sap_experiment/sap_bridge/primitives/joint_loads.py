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
from ..contracts import PointLoad
from ..sap_session import SapSessionError

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
