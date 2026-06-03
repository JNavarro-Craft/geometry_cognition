"""Read point objects (joints) from the live SAP model: name, coordinates, restraints.

Pure facts. Coordinates come back in the model's present units (see /v1/units); the
6-DOF restraint flags are reported raw — the bridge does not name them 'pinned' or
'fixed' (that is domain, and lives in the client).

pythonnet returns .NET ``ref``/``out`` parameters as a tuple appended after the
method's own return value. So ``GetNameList(0, None)`` comes back as
``(ret, number, names)``.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import Joint
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.joints")


def get_joints(sap_model: Any) -> list[Joint]:
    """Return every point object with coordinates (global Cartesian) and restraints.

    Raises SapSessionError(OAPI_CALL_FAILED) if an OAPI call returns non-zero, and
    SapSessionError(OAPI_UNEXPECTED_SHAPE) if the name list is missing when SAP
    reports points exist — reported loudly, never silently skipped.
    """
    point = sap_model.PointObj
    ret, number, names = point.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"PointObj.GetNameList reported {number} points but returned no names",
        )

    return _build_joints(point, names)


def list_joint_names(sap_model: Any) -> list[str]:
    """Just the joint names (for existence checks by write primitives, Fase 1h.2)."""
    ret, number, names = sap_model.PointObj.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"PointObj.GetNameList returned {ret}"
        )
    return [str(names[i]) for i in range(number)] if number else []


def get_joint_coords(sap_model: Any, name: str) -> tuple[float, float, float]:
    """The global Cartesian coordinates of one joint (for modify previews, Fase 1h.2)."""
    cret, x, y, z = sap_model.PointObj.GetCoordCartesian(name, 0.0, 0.0, 0.0, "Global")
    if cret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.GetCoordCartesian('{name}') returned {cret}",
        )
    return float(x), float(y), float(z)


def get_joint_restraints(sap_model: Any, name: str) -> list[bool]:
    """The 6 restraint flags [U1,U2,U3,R1,R2,R3] of one joint (Fase 1h.3). GetRestraint(Name,
    None) → (0, bool[6])."""
    rret, restraints = sap_model.PointObj.GetRestraint(name, None)
    if rret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PointObj.GetRestraint('{name}') returned {rret}",
        )
    return [bool(v) for v in restraints]


def _build_joints(point: Any, names: Any) -> list[Joint]:
    joints: list[Joint] = []
    for name in names:
        cret, x, y, z = point.GetCoordCartesian(name, 0.0, 0.0, 0.0, "Global")
        if cret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PointObj.GetCoordCartesian('{name}') returned {cret}",
            )
        rret, restraints = point.GetRestraint(name, None)
        if rret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PointObj.GetRestraint('{name}') returned {rret}",
            )
        joints.append(
            Joint(
                name=str(name),
                x=float(x),
                y=float(y),
                z=float(z),
                coord_system="Global",
                restraints=[bool(v) for v in restraints],
            )
        )
    return joints
