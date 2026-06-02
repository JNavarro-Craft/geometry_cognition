"""Read the frame section property catalogue defined in the live SAP model.

Pure facts: the section names and their SAP property type. The bridge does not
resolve geometric dimensions (a later primitive) and does not know what a name like
'MGP10_33x73' means — that is a model-supplied label, relayed verbatim.

OAPI note (verified against SAP2000 v26, see docs/brechas.md): cPropFrame.GetNameList
*filters* by the eFramePropType argument — there is no single "all types" call. So to
enumerate the full catalogue we union the result over every eFramePropType value. The
type each section belongs to falls out of which bucket returned it, so no per-section
GetTypeOAPI call is needed. Cross-checked against PropFrame.Count().
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import Section
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.sections")


def get_sections(sap_model: Any, oapi_namespace: Any) -> list[Section]:
    """Return every frame section property in the model, with its SAP type.

    ``oapi_namespace`` is the loaded SAP2000v1 module (used for the eFramePropType
    enum); passed in so this stays decoupled from how the session loaded it.
    """
    import System  # type: ignore

    prop = sap_model.PropFrame
    enum_type = oapi_namespace.eFramePropType
    type_labels = list(System.Enum.GetNames(enum_type))

    sections: dict[str, str] = {}
    for label in type_labels:
        prop_type = getattr(enum_type, label)
        ret, number, names = prop.GetNameList(0, None, prop_type)
        if ret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropFrame.GetNameList(PropType={label}) returned {ret}",
            )
        if number == 0 or not names:
            continue
        for name in names:
            # First bucket wins; a name should only appear under one type.
            sections.setdefault(str(name), label)

    # Cross-check against the model's own count; report a mismatch loudly rather than
    # silently returning a partial catalogue (the silent-bug class we hunt).
    try:
        declared = int(prop.Count())
    except Exception:  # Count is best-effort; absence shouldn't fail the call
        declared = -1
    if declared >= 0 and declared != len(sections):
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"PropFrame.Count()={declared} but enumeration found {len(sections)} "
            "sections; refusing to return a partial catalogue",
        )

    return [Section(name=n, prop_type=t) for n, t in sections.items()]


def list_section_names(sap_model: Any, oapi_namespace: Any) -> list[str]:
    """All frame section names of any type (for uniqueness/existence checks by write
    primitives). cPropFrame.GetNameList filters by type (§3), so this unions over every
    eFramePropType — same approach as get_sections."""
    return [s.name for s in get_sections(sap_model, oapi_namespace)]


def get_section_type(sap_model: Any, oapi_namespace: Any, name: str) -> str | None:
    """Return a section's raw eFramePropType member name, or None if it does not exist.

    GetTypeOAPI returns ret=1 for an unknown name (verified, §24); the enum out-param
    needs a real member placeholder."""
    placeholder = oapi_namespace.eFramePropType.Rectangular
    ret, prop_type = sap_model.PropFrame.GetTypeOAPI(name, placeholder)
    if ret != 0:
        return None
    return str(prop_type)
