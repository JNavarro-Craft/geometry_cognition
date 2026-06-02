"""Write primitives for materials — the first writes over individual OBJECTS (Fase 1g.4).

Two atomic primitives (no composite): ``create_material`` makes a named material in the
bridge's namespace, and ``set_material_properties_isotropic`` configures its mechanics. A
freshly created material has only defaults, so a usable material is the client composing
create → set_properties (client_patterns.md Pattern 4).

Namespace (write_side_design.md §1): create requires the bridge prefix (namespace.py);
modifying a material WITHOUT the prefix (a pre-existing one) requires confirm (§5.1), while
a bridge-owned one does not.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §23):

  * cPropMaterial.SetMaterial(Name, eMatType, Color, Notes, GUID) → takes the eMatType
    MEMBER (resolve by name off the live enum), returns 0. ⚠️ With an EXISTING name it
    OVERWRITES silently (no error) — hence the explicit name_already_exists guard.
  * eMatType has 8 members: Steel, Concrete, NoDesign, Aluminum, ColdFormed, Rebar,
    Tendon, Masonry. There is NO 'Wood' — timber is 'NoDesign' (what MGP10 uses).
  * cPropMaterial.SetMPIsotropic(Name, E, U, A, Temp) → 4 inputs (NO G; SAP derives
    G = E/(2(1+U))), Temp is an input (0.0), returns 0. On a non-existent material → ret=1.
    Values are in the model's PRESENT UNITS; the bridge does not convert (client's job).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    CreateMaterialResponse,
    IsotropicProperties,
    IsotropicPropertiesChange,
    MaterialCreation,
    SetMaterialPropertiesIsotropicResponse,
)
from ..namespace import (
    assert_no_conflict,
    assert_prefix_required,
    get_bridge_prefix,
    has_bridge_prefix,
)
from ..sap_session import SapSessionError
from . import materials as materials_read


def create_material(
    sap_model: Any, oapi_namespace: Any, name: str, material_type: str, dry_run: bool
) -> CreateMaterialResponse:
    """Create a material named ``name`` (bridge-prefixed) of ``material_type``.

    Raises PREFIX_REQUIRED (no prefix), UNKNOWN_MATERIAL_TYPE (bad type), NAME_ALREADY_EXISTS
    (taken — SAP would overwrite silently otherwise), OAPI_CALL_FAILED (SetMaterial failed).
    No confirm (creating a new prefixed object is non-destructive).
    """
    with audited(
        "create_material",
        {"name": name, "material_type": material_type, "dry_run": dry_run},
    ) as ctx:
        assert_prefix_required(name)

        member = materials_read.resolve_material_type(oapi_namespace, material_type)
        if member is None:
            supported = ", ".join(materials_read.material_type_names(oapi_namespace))
            raise SapSessionError(
                error_codes.UNKNOWN_MATERIAL_TYPE,
                f"unknown material type '{material_type}'; supported: {supported} "
                "(SAP26 has no 'Wood' — use 'NoDesign' for timber)",
            )
        type_code = int(member)

        assert_no_conflict(name, materials_read.list_material_names(sap_model))

        creation = MaterialCreation(name=name, material_type=material_type, type_code=type_code)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": name, "material_type": material_type}
            return CreateMaterialResponse(dry_run=True, validation_passed=True, would_apply=creation)

        sret = sap_model.PropMaterial.SetMaterial(name, member, -1, "", "")
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropMaterial.SetMaterial('{name}') returned {ret_code}",
            )
        ctx["result_details"] = {"name": name, "material_type": material_type}
        return CreateMaterialResponse(dry_run=False, applied=creation)


def _read_isotropic(sap_model: Any, name: str) -> IsotropicProperties | None:
    """Read a material's current isotropic properties, or None if it has none yet."""
    try:
        iret, e, u, a, g = sap_model.PropMaterial.GetMPIsotropic(name, 0.0, 0.0, 0.0, 0.0, 0.0)
    except Exception:  # noqa: BLE001 — not isotropic / not set yet
        return None
    if iret != 0:
        return None
    return IsotropicProperties(
        e=float(e), poisson_ratio=float(u), thermal_coef=float(a), shear_modulus=float(g)
    )


def _diff(old: IsotropicProperties | None, e: float, u: float, a: float) -> list[str]:
    """Per-field diff old → new for the three inputs (G is derived, not an input)."""
    fields = [("E", old.e if old else None, e),
              ("poisson_ratio", old.poisson_ratio if old else None, u),
              ("thermal_coef", old.thermal_coef if old else None, a)]
    out = []
    for label, ov, nv in fields:
        if ov is None:
            out.append(f"{label}: (unset) → {nv}")
        elif ov != nv:
            out.append(f"{label}: {ov} → {nv}")
    return out


def set_material_properties_isotropic(
    sap_model: Any, name: str, e: float, poisson_ratio: float, thermal_coef: float,
    dry_run: bool, confirm: bool
) -> SetMaterialPropertiesIsotropicResponse:
    """Set the isotropic mechanical properties of an existing material.

    Confirm rules (§5.1): a non-prefixed (pre-existing) material requires confirm; a
    bridge-owned one does not. Raises OBJECT_NOT_FOUND if the material does not exist,
    CONFIRM_REQUIRED, OAPI_CALL_FAILED. Values are in present units (client's job to know).
    """
    with audited(
        "set_material_properties_isotropic",
        {"name": name, "E": e, "poisson_ratio": poisson_ratio,
         "thermal_coef": thermal_coef, "dry_run": dry_run, "confirm": confirm},
    ) as ctx:
        if name not in materials_read.list_material_names(sap_model):
            raise SapSessionError(
                error_codes.OBJECT_NOT_FOUND,
                f"material '{name}' does not exist (list with GET /v1/materials)",
            )

        current = _read_isotropic(sap_model, name)
        changes = _diff(current, e, poisson_ratio, thermal_coef)
        new_props = IsotropicProperties(
            e=e, poisson_ratio=poisson_ratio, thermal_coef=thermal_coef, shear_modulus=None
        )

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"changes": changes}
            return SetMaterialPropertiesIsotropicResponse(
                dry_run=True,
                validation_passed=True,
                would_apply=IsotropicPropertiesChange(
                    current_properties=current, new_properties=new_props, changes=changes
                ),
            )

        # Modifying a pre-existing (non-bridge) material is destructive → confirm (§5.1).
        if not has_bridge_prefix(name) and not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"material '{name}' is not bridge-owned (no '{get_bridge_prefix()}' prefix); "
                "modifying a pre-existing material requires confirm=true",
            )

        sret = sap_model.PropMaterial.SetMPIsotropic(name, e, poisson_ratio, thermal_coef, 0.0)
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropMaterial.SetMPIsotropic('{name}') returned {ret_code}",
            )

        applied_now = _read_isotropic(sap_model, name)
        ctx["result_details"] = {"changes": changes}
        return SetMaterialPropertiesIsotropicResponse(
            dry_run=False,
            applied=IsotropicPropertiesChange(
                previous_properties=current, current_properties=applied_now, changes=changes
            ),
        )
