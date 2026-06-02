"""Read the composition of ONE load case (patterns + factors it applies), from the model.

Closes the asymmetry get_combinations left: combinations already exposed their full
composition, load cases did not. This resolves a LinearStatic case's applied loads. For
any other case type the bridge reports the type and flags it unsupported this phase —
information, not an error (the case exists; its internals are deferred).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §11):

  * The case type comes from cLoadCases.GetTypeOAPI (as in get_load_cases). Composition
    of a LinearStatic case is read via cLoadCases.StaticLinear.GetLoads(Name, ref
    NumberLoads, ref LoadType[], ref LoadName[], ref SF[]) — three parallel arrays.
    Verified: each TEST_01 LinearStatic case applies one pattern of the same name, SF=1.0,
    LoadType='Load'.
  * Other case types (Modal, ResponseSpectrum, …) have their own OAPI classes; this phase
    does not read them. StaticLinear.GetLoads on a non-LinearStatic case returns non-zero,
    so the type guard (not the return code) is the gate.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import LoadCaseDetails, LoadCaseLoadItem
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.load_case_details")

_SUPPORTED_CASE_TYPE = "LinearStatic"


def get_load_case_details(sap_model: Any, oapi_namespace: Any, case_name: str) -> LoadCaseDetails:
    """Return the composition of ``case_name``.

    LinearStatic cases return their applied load items; other types return the correct
    case_type with unsupported_case_type=True and an empty loads list. Raises
    SapSessionError(OAPI_CALL_FAILED) if the case is unknown or an OAPI call fails.
    """
    lc = sap_model.LoadCases
    type_placeholder = oapi_namespace.eLoadCaseType.LinearStatic

    tret, case_type, _subtype = lc.GetTypeOAPI(case_name, type_placeholder, 0)
    if tret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadCases.GetTypeOAPI('{case_name}') returned {tret} "
            "(unknown case? cross-check /v1/load_cases)",
        )
    case_type = str(case_type)

    if case_type != _SUPPORTED_CASE_TYPE:
        return LoadCaseDetails(
            case_name=case_name,
            case_type=case_type,
            unsupported_case_type=True,
            loads=[],
        )

    lret, nloads, load_types, load_names, sfs = lc.StaticLinear.GetLoads(case_name, 0, None, None, None)
    if lret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadCases.StaticLinear.GetLoads('{case_name}') returned {lret}",
        )

    items: list[LoadCaseLoadItem] = []
    if nloads > 0:
        if any(a is None or len(a) < nloads for a in (load_types, load_names, sfs)):
            raise SapSessionError(
                error_codes.OAPI_UNEXPECTED_SHAPE,
                f"StaticLinear.GetLoads('{case_name}') reported {nloads} loads but a "
                "parallel array is missing or shorter",
            )
        items = [
            LoadCaseLoadItem(
                load_type=str(load_types[i]),
                load_pattern=str(load_names[i]),
                scale_factor=float(sfs[i]),
            )
            for i in range(nloads)
        ]

    return LoadCaseDetails(
        case_name=case_name,
        case_type=case_type,
        unsupported_case_type=False,
        loads=items,
    )
