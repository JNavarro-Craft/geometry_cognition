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
from ..contracts import DistributedLoad
from ..sap_session import SapSessionError

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
