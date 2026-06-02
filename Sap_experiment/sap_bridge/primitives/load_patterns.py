"""Read the load pattern catalogue defined in the live SAP model.

Pure facts: each pattern's name, its raw SAP load type and its self-weight multiplier.
The bridge does not translate a name ('PESO PROPIO' stays 'PESO PROPIO', not 'Dead')
and does not know which patterns a model "should" have — the patterns are a fact of the
model, never created or assumed by the bridge (brief, Principle 1; the SapConfigurator
leak we refuse).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §9):

  * cLoadPatterns.GetNameList(ref NumberNames, ref MyName) — no type filter, returns all.
  * GetLoadType(name, ref eLoadPatternType) — the eLoadPatternType out-param needs a real
    enum member as pythonnet placeholder (an int is rejected; same rule as §5).
  * GetSelfWTMultiplier(name, ref Double) — note the capital WT.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import LoadPattern
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.load_patterns")


def get_load_patterns(sap_model: Any, oapi_namespace: Any) -> list[LoadPattern]:
    """Return every load pattern with its SAP type and self-weight multiplier.

    ``oapi_namespace`` is the loaded SAP2000v1 module, needed for the eLoadPatternType
    enum placeholder the OAPI out-param requires.
    """
    lp = sap_model.LoadPatterns
    type_placeholder = oapi_namespace.eLoadPatternType.Dead

    ret, number, names = lp.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"LoadPatterns.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"LoadPatterns.GetNameList reported {number} patterns but returned no names",
        )

    patterns: list[LoadPattern] = []
    for name in names:
        name = str(name)
        tret, load_type = lp.GetLoadType(name, type_placeholder)
        if tret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadPatterns.GetLoadType('{name}') returned {tret}",
            )
        sret, sw_mult = lp.GetSelfWTMultiplier(name, 0.0)
        if sret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"LoadPatterns.GetSelfWTMultiplier('{name}') returned {sret}",
            )
        patterns.append(
            LoadPattern(
                name=name,
                load_type=str(load_type),
                self_weight_multiplier=float(sw_mult),
            )
        )
    return patterns
