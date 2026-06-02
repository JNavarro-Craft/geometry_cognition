"""Read frame (line) objects from the live SAP model: name, end points, section.

Pure facts: connectivity (the two end point names) and the assigned section property
name. The bridge does not classify a frame as chord/strut/diagonal — that emerges in
the client from connectivity + dimensions, never here (brief, Principle 1).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import Frame
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.frames")


def get_frames(sap_model: Any) -> list[Frame]:
    """Return every frame object with its i/j end point names and assigned section.

    ``GetPoints`` gives the connectivity (point names, matching get_joints); the
    client resolves coordinates by joining on those names. ``GetSection`` returns the
    section property name plus the auto-select list name ('' if none) — both raw.
    """
    frame = sap_model.FrameObj
    ret, number, names = frame.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"FrameObj.GetNameList reported {number} frames but returned no names",
        )

    frames: list[Frame] = []
    for name in names:
        pret, p_i, p_j = frame.GetPoints(name, "", "")
        if pret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"FrameObj.GetPoints('{name}') returned {pret}",
            )
        sret, prop_name, auto = frame.GetSection(name, "", "")
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"FrameObj.GetSection('{name}') returned {sret}",
            )
        frames.append(
            Frame(
                name=str(name),
                point_i=str(p_i),
                point_j=str(p_j),
                section=str(prop_name),
                auto_select=str(auto),
            )
        )
    return frames


def list_frame_names(sap_model: Any) -> list[str]:
    """Just the frame names (for existence checks by write primitives)."""
    ret, number, names = sap_model.FrameObj.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"FrameObj.GetNameList returned {ret}"
        )
    return [str(names[i]) for i in range(number)] if number else []


def get_frame_section(sap_model: Any, frame_name: str) -> str:
    """The section property name currently assigned to ``frame_name`` (raw)."""
    ret, prop_name, _auto = sap_model.FrameObj.GetSection(frame_name, "", "")
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.GetSection('{frame_name}') returned {ret}",
        )
    return str(prop_name)
