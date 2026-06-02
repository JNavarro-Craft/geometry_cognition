"""Read model configuration: structural envelope (active DOFs + lock state) and units.

Pure facts. The bridge reports the raw active-DOF vector and the lock state as SAP gives
them, and never derives an interpretation: it does not say a model is '2D', 'Plane Frame
XZ' or 'Space Frame' — that pattern recognition is the client's, read off the active_dof
vector (brief, Principle 1; the leak we refuse).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §17):

  * cAnalyze.GetActiveDOF(ref Boolean[] DOF) -> (ret, dof[6]) in order
    [U1, U2, U3, R1, R2, R3] — the same index convention as joint restraints/results.
  * cSapModel.GetPresentUnits() / GetDatabaseUnits() each return the eUnits enum directly
    (the member already includes temperature, e.g. 'kgf_m_C'). The documented `_2`
    variants do NOT exist in this assembly, so no separate temperature read is needed.
  * cSapModel.GetModelIsLocked() -> bool, callable in any model state.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import ModelSettings
from ..sap_session import SapSessionError
from . import units as units_primitive

logger = logging.getLogger("sap_bridge.primitives.model_settings")

_DOF_COUNT = 6


def get_model_settings(sap_model: Any) -> ModelSettings:
    """Return the model's active DOFs, lock state, and present + database units."""
    ret, dof = sap_model.Analyze.GetActiveDOF(None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"Analyze.GetActiveDOF returned {ret}",
        )
    if dof is None or len(dof) != _DOF_COUNT:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"Analyze.GetActiveDOF returned {0 if dof is None else len(dof)} flags, "
            f"expected {_DOF_COUNT}",
        )

    return ModelSettings(
        active_dof=[bool(dof[i]) for i in range(_DOF_COUNT)],
        model_is_locked=bool(sap_model.GetModelIsLocked()),
        present_units=units_primitive.get_present_units(sap_model),
        database_units=units_primitive.get_database_units(sap_model),
    )
