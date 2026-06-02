"""Read the material property catalogue defined in the live SAP model.

Pure facts: each material's name, its raw SAP material type (eMatType member name) and
basic mechanical properties as SAP reports them. The bridge does not interpret a name:
'MGP10' is a model-supplied label that SAP itself classifies as 'NoDesign' — relayed
verbatim, never renamed to 'timber' or similar (brief, Principle 1; the leak we refuse).

OAPI notes (verified against SAP2000 v26, see docs/brechas.md):

  * cPropMaterial.GetMaterial(name, ref MatType, ref Color, ref Notes, ref GUID) returns
    the eMatType directly — used instead of GetTypeOAPI, whose extra out-param made its
    pythonnet placeholder fiddly. The eMatType out-param needs a real enum member as
    placeholder; we pass eMatType.Steel (any member works, it is overwritten).
  * GetMPIsotropic(name, ref E, ref U, ref A, ref G, Temp) — Temp is an INPUT (0.0).
    Returns the isotropic mechanical set. Only meaningful for isotropic materials; for
    others the call may fail, and we report null rather than fabricate values.
  * GetWeightAndMass(name, ref W, ref M, Temp) — Temp INPUT; weight + mass per volume.

Mechanical values come back in the model's present units; the bridge exposes, never
converts (the client converts knowing what it holds).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..contracts import Material
from ..sap_session import SapSessionError

logger = logging.getLogger("sap_bridge.primitives.materials")


def get_materials(sap_model: Any, oapi_namespace: Any) -> list[Material]:
    """Return every material property with its SAP type and basic mechanical facts.

    ``oapi_namespace`` is the loaded SAP2000v1 module, needed for the eMatType enum
    placeholder the OAPI out-param requires.

    Raises SapSessionError(OAPI_CALL_FAILED) if the name enumeration fails, and
    OAPI_UNEXPECTED_SHAPE if SAP reports materials exist but returns no names. Per-
    material mechanical calls that fail are reported as null fields (not every material
    is isotropic), never silently substituted.
    """
    mat = sap_model.PropMaterial
    mat_type_placeholder = oapi_namespace.eMatType.Steel

    ret, number, names = mat.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"PropMaterial.GetNameList returned {ret}",
        )
    if number == 0:
        return []
    if names is None:
        raise SapSessionError(
            error_codes.OAPI_UNEXPECTED_SHAPE,
            f"PropMaterial.GetNameList reported {number} materials but returned no names",
        )

    materials: list[Material] = []
    for name in names:
        name = str(name)

        # Material type is mandatory: a material always has one. Failing here is a real
        # OAPI failure, surfaced loudly.
        tret, mat_type, _color, _notes, _guid = mat.GetMaterial(name, mat_type_placeholder, 0, "", "")
        if tret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropMaterial.GetMaterial('{name}') returned {tret}",
            )

        # Mechanical props are best-effort: GetMPIsotropic only applies to isotropic
        # materials. A non-zero return or an exception means "not available for this
        # material" — we report null, never a fabricated default.
        e = nu = thermal = shear = None
        try:
            iret, e_v, u_v, a_v, g_v = mat.GetMPIsotropic(name, 0.0, 0.0, 0.0, 0.0, 0.0)
            if iret == 0:
                e, nu, thermal, shear = float(e_v), float(u_v), float(a_v), float(g_v)
        except Exception as exc:  # noqa: BLE001 — non-isotropic / unsupported: null, not fake
            logger.debug("GetMPIsotropic('%s') unavailable: %s", name, exc)

        weight = mass = None
        try:
            wret, w_v, m_v = mat.GetWeightAndMass(name, 0.0, 0.0, 0.0)
            if wret == 0:
                weight, mass = float(w_v), float(m_v)
        except Exception as exc:  # noqa: BLE001
            logger.debug("GetWeightAndMass('%s') unavailable: %s", name, exc)

        materials.append(
            Material(
                name=name,
                mat_type=str(mat_type),
                e=e,
                nu=nu,
                thermal_coeff=thermal,
                shear_modulus=shear,
                weight_per_volume=weight,
                mass_per_volume=mass,
            )
        )
    return materials


def list_material_names(sap_model: Any) -> list[str]:
    """Just the material names (for uniqueness / existence checks by write primitives)."""
    ret, number, names = sap_model.PropMaterial.GetNameList(0, None)
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"PropMaterial.GetNameList returned {ret}"
        )
    return [str(names[i]) for i in range(number)] if number else []


def material_type_names(oapi_namespace: Any) -> list[str]:
    """The eMatType member names this assembly supports (Steel, Concrete, NoDesign, …).
    Read off the live enum so it matches exactly what the read-side reports — no table.
    NOTE: there is NO 'Wood' member in SAP26 (brechas §23); timber is modelled as
    'NoDesign' (that is what MGP10 uses)."""
    import clr  # type: ignore
    import System  # type: ignore

    return list(System.Enum.GetNames(clr.GetClrType(oapi_namespace.eMatType)))


def resolve_material_type(oapi_namespace: Any, type_name: str) -> Any | None:
    """Resolve an eMatType NAME to its enum member, or None if unknown. Inverse of what
    the read-side exposes (mat_type via str(enum)); via getattr on the live enum, so the
    accepted set is exactly SAP's. SetMaterial needs the MEMBER, not an int."""
    return getattr(oapi_namespace.eMatType, type_name, None)
