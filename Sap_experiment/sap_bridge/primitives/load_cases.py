"""Read the analysis load case catalogue defined in the live SAP model.

Pure facts: each case's name and raw SAP case type. The bridge does not resolve a
case's internal definition (which patterns/factors it applies) — that is a later
primitive — and does not interpret the name.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §9):

  * cLoadCases.GetNameList has a type-filtered overload (GetNameList(n, names, CaseType))
    AND a 2-arg overload that returns ALL cases. We call the 2-arg form for the full
    catalogue (filtering to LinearStatic returned 6, the unfiltered call 7 — the extra
    one being the MODAL case). Same filter-vs-all subtlety as cPropFrame in §3.
  * GetTypeOAPI(name, ref eLoadCaseType, ref Int32 SubType) — two out-params; we report
    the eLoadCaseType (the SubType is an internal discriminator we do not surface this
    phase). The enum out-param needs a real enum member placeholder (§5).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import LoadCase
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.load_cases")


def get_load_cases(sap_model: Any, oapi_namespace: Any) -> list[LoadCase]:
    """Return every analysis load case with its raw SAP case type.

    ``oapi_namespace`` is the loaded SAP2000v1 module, needed for the eLoadCaseType enum
    placeholder. The unfiltered GetNameList overload is used so MODAL and every other
    type are included (the type-filtered overload would return only one type).
    """
    lc = sap_model.LoadCases
    type_placeholder = oapi_namespace.eLoadCaseType.LinearStatic

    ret, number, names = lc.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadCases.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"LoadCases.GetNameList reported {number} cases but returned no names",
        )

    cases: list[LoadCase] = []
    for name in names:
        name = str(name)
        # GetTypeOAPI returns (ret, eLoadCaseType, SubType); we surface the type only.
        tret, case_type, _subtype = lc.GetTypeOAPI(name, type_placeholder, 0)
        if tret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadCases.GetTypeOAPI('{name}') returned {tret}",
            )
        cases.append(LoadCase(name=name, case_type=str(case_type)))
    return cases
