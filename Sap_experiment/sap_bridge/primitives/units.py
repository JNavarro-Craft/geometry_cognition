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


def _units_response(units_enum: Any) -> UnitsResponse:
    """Wrap a raw eUnits enum as a UnitsResponse (name + integer code).

    pythonnet exposes the enum value; str() gives the member name (e.g. 'kgf_m_C',
    which already carries the temperature unit — the 'C' is Celsius). The bridge does
    not interpret the system, only relays both forms so a client can match on either.
    """
    return UnitsResponse(present_units=str(units_enum), present_units_code=int(units_enum))


def get_present_units(sap_model: Any) -> UnitsResponse:
    """Return the present units of the model. ``cSapModel.GetPresentUnits()`` returns the
    eUnits enum directly (no out-param)."""
    return _units_response(sap_model.GetPresentUnits())


def get_database_units(sap_model: Any) -> UnitsResponse:
    """Return the database units — the system the model stores data in internally, vs the
    present 'view'. ``cSapModel.GetDatabaseUnits()`` returns the eUnits enum directly.

    OAPI note (SAP26, brechas §17): the documented ``_2`` variants (which would also
    return temperature separately) do NOT exist in this assembly; the plain getters
    return the full eUnits member, temperature included, so no ``_2`` is needed.
    """
    return _units_response(sap_model.GetDatabaseUnits())
