"""Read the load combination catalogue defined in the live SAP model.

Pure facts: each combination's name, type and component items (referenced case/combo +
scale factor). The bridge consolidates SAP's parallel arrays into a list of objects so
the client never recomposes indices, and it interprets nothing: a combo named
'ENVOLVENTE' is reported with combo_type 'Envelope', never labelled a seismic ULS or
anything domain (brief, Principle 1; anti-pattern #4 — no inference from names).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §9-10):

  * The combination interface is cCombo, reached via model.RespCombo.
  * GetTypeOAPI(name, ref Int32 ComboType) returns a raw INTEGER, not an enum — this
    assembly exposes no eComboType. The integer follows the OAPI's documented mapping
    (see _COMBO_TYPE_NAMES). We surface both the raw code and the mapped name.
  * GetCaseList(name, ref NumberItems, ref eCNameType[] CNameType, ref String[] CName,
    ref Double[] SF) returns three PARALLEL arrays after the count. eCNameType is
    'LoadCase' or 'LoadCombo' (combo-of-combo is real: e.g. 'D+L' references combo 'D').
    The enum array out-param accepts None as placeholder (unlike scalar enum out-params).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import ComboItem, Combination
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.combinations")

# SAP2000 OAPI documented eComboType integer mapping. This assembly returns a bare int
# from GetTypeOAPI (no enum), so the bridge maps it to SAP's own type name — the same
# kind of relay as turning an eMatType into its member name, not domain interpretation.
# An out-of-range code maps to 'Unknown' and is reported, never guessed.
_COMBO_TYPE_NAMES = {
    0: "Linear Additive",
    1: "Envelope",
    2: "Absolute Additive",
    3: "SRSS",
    4: "Range Additive",
}


def get_combinations(sap_model: Any) -> list[Combination]:
    """Return every load combination with its type and consolidated component items.

    No oapi_namespace needed: GetTypeOAPI returns a plain int and GetCaseList accepts
    None placeholders for its array out-params.
    """
    rc = sap_model.RespCombo

    ret, number, names = rc.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"RespCombo.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"RespCombo.GetNameList reported {number} combinations but returned no names",
        )

    combinations: list[Combination] = []
    for name in names:
        name = str(name)

        tret, combo_code = rc.GetTypeOAPI(name, 0)
        if tret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"RespCombo.GetTypeOAPI('{name}') returned {tret}",
            )
        combo_code = int(combo_code)
        combo_type = _COMBO_TYPE_NAMES.get(combo_code, "Unknown")

        cret, nitems, cname_types, cnames, sfs = rc.GetCaseList(name, 0, None, None, None)
        if cret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"RespCombo.GetCaseList('{name}') returned {cret}",
            )

        # Parallel arrays must agree in length; a mismatch is the silent-bug class we
        # hunt — report it loudly rather than zipping to the shortest.
        if nitems > 0 and (
            cname_types is None or cnames is None or sfs is None
            or len(cname_types) < nitems or len(cnames) < nitems or len(sfs) < nitems
        ):
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"RespCombo.GetCaseList('{name}') reported {nitems} items but the parallel "
                "CNameType/CName/SF arrays are missing or shorter",
            )

        items = [
            ComboItem(
                case_name=str(cnames[i]),
                case_type=str(cname_types[i]),
                scale_factor=float(sfs[i]),
            )
            for i in range(nitems)
        ]

        combinations.append(
            Combination(
                name=name,
                combo_type=combo_type,
                combo_type_code=combo_code,
                items=items,
            )
        )
    return combinations
