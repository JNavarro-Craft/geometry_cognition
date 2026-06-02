"""Read dimensions + universal properties of ONE frame section from the live model.

Pure facts: shape-specific geometry (depth/width, diameter, …) plus the universal
section properties (area, inertias, moduli, radii of gyration). The bridge does not
interpret a section name and does not normalize geometry across shapes — the dimension
keys are SAP's own parameter names, relayed verbatim.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md):

  * cPropFrame.GetTypeOAPI(name, ref eFramePropType) returns the section's shape type.
    The eFramePropType out-param needs a real enum member as placeholder (an int is
    rejected by pythonnet); we pass eFramePropType.Rectangular (overwritten on return).
  * cPropFrame.GetRectangle(name, ref FileName, ref MatProp, ref T3, ref T2, ref Color,
    ref Notes, ref GUID): T3 = depth, T2 = width, MatProp = material name. Verified
    MGP10_33x73 -> T3=0.073, T2=0.033, MatProp='MGP10'.
  * cPropFrame.GetSectProps(name, ref Area, ref As2, ref As3, ref Torsion, ref I22,
    ref I33, ref S22, ref S33, ref Z22, ref Z33, ref R22, ref R33): the universal
    properties, available for any shape. Verified MGP10_33x73 -> Area=0.002409
    (= 0.073 x 0.033), matching the manual cross-check.

Per-shape dimension extraction is dispatched on the section type. Only the shapes
implemented this phase are supported; any other type returns a structured
OAPI_UNEXPECTED_SHAPE carrying the received type, rather than guessing or returning a
partial answer (the silent-bug class we hunt). Adding a shape is purely additive.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .. import error_codes
from ..contracts import SectionProperties
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.section_properties")

# Universal section-property field names, in GetSectProps return order (after ret).
_SECT_PROP_FIELDS = (
    "area", "as2", "as3", "torsion", "i22", "i33", "s22", "s33", "z22", "z33", "r22", "r33",
)


def _dims_rectangle(prop: Any, name: str) -> tuple[str, dict[str, float]]:
    """Rectangular: T3 = depth, T2 = width. Returns (material_name, dimensions)."""
    ret, _file, mat_prop, t3, t2, _color, _notes, _guid = prop.GetRectangle(
        name, "", "", 0.0, 0.0, 0, "", ""
    )
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PropFrame.GetRectangle('{name}') returned {ret}",
        )
    return str(mat_prop), {"depth": float(t3), "width": float(t2)}


# Dispatch table: eFramePropType member name -> dimension extractor. Additive by design.
_SHAPE_EXTRACTORS: dict[str, Callable[[Any, str], tuple[str, dict[str, float]]]] = {
    "Rectangular": _dims_rectangle,
}


def get_section_properties(sap_model: Any, oapi_namespace: Any, name: str) -> SectionProperties:
    """Return geometry + universal properties for the named frame section.

    Raises SapSessionError(OAPI_CALL_FAILED) if the section is unknown or an OAPI call
    fails, and OAPI_UNEXPECTED_SHAPE if the section's shape type is not implemented this
    phase (the message carries the received type).
    """
    prop = sap_model.PropFrame
    frame_type_placeholder = oapi_namespace.eFramePropType.Rectangular

    # Shape type first: it both selects the extractor and validates the name exists.
    tret, prop_type = prop.GetTypeOAPI(name, frame_type_placeholder)
    if tret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PropFrame.GetTypeOAPI('{name}') returned {tret} "
            "(unknown section name? cross-check /v1/sections)",
        )
    type_label = str(prop_type)

    extractor = _SHAPE_EXTRACTORS.get(type_label)
    if extractor is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"section '{name}' has type '{type_label}', not supported this phase "
            f"(implemented: {', '.join(sorted(_SHAPE_EXTRACTORS))})",
        )

    material, dimensions = extractor(prop, name)

    # Universal section properties — available for any shape.
    sret, *vals = prop.GetSectProps(name, *([0.0] * len(_SECT_PROP_FIELDS)))
    if sret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PropFrame.GetSectProps('{name}') returned {sret}",
        )
    properties = {field: float(v) for field, v in zip(_SECT_PROP_FIELDS, vals)}

    return SectionProperties(
        name=name,
        prop_type=type_label,
        material=material,
        dimensions=dimensions,
        properties=properties,
    )
