"""Read the active SAP2000 unit system as a bare fact.

Exposing units (rather than converting silently) is Principle 3 of the brief and the
lesson distilled from RhinoSAP/Utils/UnitConversion.cs: the bridge states what units
the model is in; the client converts knowing what it holds on each side.
"""
from __future__ import annotations

import logging
from typing import Any

from ..contracts import UnitsResponse

logger = logging.getLogger("sap_bridge.primitives.units")


def get_present_units(sap_model: Any) -> UnitsResponse:
    """Return the present units of the model.

    ``cSapModel.GetPresentUnits()`` returns the eUnits enum directly (no out-param).
    We report both the enum's name and its integer value so a client can match on
    either without the bridge interpreting the system.
    """
    units_enum = sap_model.GetPresentUnits()
    # pythonnet exposes the enum value; str() gives the member name (e.g. 'kgf_m_C').
    name = str(units_enum)
    code = int(units_enum)
    return UnitsResponse(present_units=name, present_units_code=code)
