"""Read frame internal forces from the analysed model (read-only post-analysis).

Internal forces (axial, shears, torsion, moments) at the stations SAP computed along a
frame, in one load case. Same computation-state dependency and case guard as the joint
results (a case not run → case_not_run). Facts only — a large moment is not "failure".

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §14-15):

  * cAnalysisResults.FrameForce(Name, eItemTypeElm, ref NumberResults, ref Obj[],
    ref ObjSta[], ref Elm[], ref ElmSta[], ref LoadCase[], ref StepType[], ref StepNum[],
    ref P[], ref V2[], ref V3[], ref T[], ref M2[], ref M3[]): the tuple has 15 elements.
    Indices: 0=ret 1=n 2=Obj 3=ObjSta 4=Elm 5=ElmSta 6=LoadCase 7=StepType 8=StepNum
    9=P 10=V2 11=V3 12=T 13=M2 14=M3. ObjSta is the absolute distance from the i-end.
  * Multiple stations per frame (verified: frame 4133 → 2 stations). The relative
    distance is derived as ObjSta / frame_length (length read from FrameObj points).
  * Requires the case selected for output (same as joint results).
"""
from __future__ import annotations

import logging
import math
from typing import Any

from .. import error_codes
from ..contracts import FrameForceStation
from ..sap_session import SapSessionError
from .joint_results import ensure_case_ready, select_case_for_output

logger = logging.getLogger("sap_bridge.primitives.frame_results")


def _frame_length(sap_model: Any, frame_name: str) -> float:
    """Length of the frame from its end points (for relative-distance derivation)."""
    fret, pi, pj = sap_model.FrameObj.GetPoints(frame_name, "", "")
    if fret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.GetPoints('{frame_name}') returned {fret}",
        )
    point = sap_model.PointObj
    ir, xi, yi, zi = point.GetCoordCartesian(pi, 0.0, 0.0, 0.0, "Global")
    jr, xj, yj, zj = point.GetCoordCartesian(pj, 0.0, 0.0, 0.0, "Global")
    if ir != 0 or jr != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.GetCoordCartesian for frame '{frame_name}' ends returned {ir}/{jr}",
        )
    return math.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2)


def get_frame_forces(
    sap_model: Any, oapi_namespace: Any, frame_name: str, case_name: str, station: float | None = None
) -> list[FrameForceStation]:
    """Return internal forces at the stations along ``frame_name`` in ``case_name``.

    ``station`` None returns every station SAP computed; a value (0..1) returns only the
    station whose relative distance matches (closest within tolerance). LinearStatic only.
    """
    ensure_case_ready(sap_model, oapi_namespace, case_name)
    select_case_for_output(sap_model, case_name)
    obj_elm = oapi_namespace.eItemTypeElm.ObjectElm

    res = sap_model.Results.FrameForce(
        frame_name, obj_elm, 0, None, None, None, None, None, None, None,
        None, None, None, None, None, None,
    )
    ret, n = res[0], res[1]
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Results.FrameForce('{frame_name}') returned {ret}",
        )
    if n == 0:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Results.FrameForce('{frame_name}') returned no rows after case selection",
        )

    obj_sta, p, v2, v3, t, m2, m3 = res[3], res[9], res[10], res[11], res[12], res[13], res[14]
    arrays = (obj_sta, p, v2, v3, t, m2, m3)
    if any(a is None or len(a) < n for a in arrays):
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Results.FrameForce('{frame_name}') reported {n} stations but a parallel "
            "array is missing or shorter",
        )

    length = _frame_length(sap_model, frame_name)
    stations: list[FrameForceStation] = []
    for i in range(n):
        abs_d = float(obj_sta[i])
        rel_d = (abs_d / length) if length > 0 else 0.0
        stations.append(
            FrameForceStation(
                relative_distance=rel_d,
                absolute_distance=abs_d,
                p=float(p[i]), v2=float(v2[i]), v3=float(v3[i]),
                t=float(t[i]), m2=float(m2[i]), m3=float(m3[i]),
            )
        )

    if station is not None:
        # Return only the station closest to the requested relative distance.
        target = min(stations, key=lambda s: abs(s.relative_distance - station))
        if abs(target.relative_distance - station) > 1e-6:
            logger.info(
                "frame '%s' has no station exactly at %s; nearest is %s",
                frame_name, station, target.relative_distance,
            )
        return [target]

    return stations
