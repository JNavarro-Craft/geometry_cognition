"""Write primitives for rectangular sections (Fase 1g.5) — second object type under the
create+modify template (after materials in 1g.4), confirming it generalizes.

create_rectangular_section makes a prefixed section with a required material; modify_
rectangular_section changes fields of an existing one (merging with current state).
Both go through namespace.py and audit_log, same as materials_write.

OAPI notes (verified against SAP2000 v26, see docs/brechas.md §24):

  * cPropFrame.SetRectangle(Name, MatProp, T3, T2, Color, Notes, GUID) → T3 = depth,
    T2 = width, returns 0. ⚠️ With an EXISTING name it OVERWRITES silently (like
    SetMaterial §23) — hence the name_already_exists guard on create. A non-existent
    MatProp → ret=1 (but we also pre-check via get_materials for a clearer error).
  * cPropFrame.GetRectangle(Name, ref FileName, ref MatProp, ref T3, ref T2, ref Color,
    ref Notes, ref GUID) — read back after a write to report SAP's actual values. Color
    defaults to 255 when -1 is passed.
  * cPropFrame.GetTypeOAPI(Name, ref eFramePropType) → ret=1 for an unknown name; used to
    check existence + that a section is Rectangular before modifying it.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..contracts import (
    CreateRectangularSectionResponse,
    ModifyRectangularSectionResponse,
    RectangularSection,
    RectangularSectionChange,
)
from ..namespace import assert_no_conflict, assert_prefix_required, get_bridge_prefix, has_bridge_prefix
from ..sap_session import SapSessionError
from . import materials as materials_read
from . import sections as sections_read

_RECTANGULAR = "Rectangular"
_DEFAULT_COLOR = -1  # SAP picks a default (255) when -1 is passed.


def _assert_positive(label: str, value: float) -> None:
    if value is not None and value <= 0:
        raise SapSessionError(
            error_codes.INVALID_DIMENSIONS,
            f"{label} must be > 0; got {value}",
        )


def _assert_material_exists(sap_model: Any, material: str) -> None:
    if material not in materials_read.list_material_names(sap_model):
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"material '{material}' does not exist (list with GET /v1/materials)",
        )


def _read_rectangle(sap_model: Any, name: str) -> RectangularSection:
    """Read a rectangular section's defining fields back from SAP."""
    ret, _file, mat, t3, t2, color, notes, _guid = sap_model.PropFrame.GetRectangle(
        name, "", "", 0.0, 0.0, 0, "", ""
    )
    if ret != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED, f"PropFrame.GetRectangle('{name}') returned {ret}"
        )
    return RectangularSection(
        name=name, material=str(mat), depth=float(t3), width=float(t2),
        color=int(color), notes=str(notes), section_type=_RECTANGULAR,
    )


def create_rectangular_section(
    sap_model: Any, oapi_namespace: Any, name: str, material: str, depth: float,
    width: float, color: int | None, notes: str, dry_run: bool
) -> CreateRectangularSectionResponse:
    """Create a rectangular section. Prefix-gated, material + dimension validated, unique-
    name guarded (SAP would otherwise overwrite silently). No confirm (new prefixed object).
    """
    with audited(
        "create_rectangular_section",
        {"name": name, "material": material, "depth": depth, "width": width,
         "color": color, "notes": notes, "dry_run": dry_run},
    ) as ctx:
        assert_prefix_required(name)
        _assert_positive("depth", depth)
        _assert_positive("width", width)
        _assert_material_exists(sap_model, material)
        assert_no_conflict(name, sections_read.list_section_names(sap_model, oapi_namespace))

        color_val = _DEFAULT_COLOR if color is None else color
        preview = RectangularSection(
            name=name, material=material, depth=depth, width=width,
            color=(255 if color is None else color), notes=notes, section_type=_RECTANGULAR,
        )

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": name, "material": material, "depth": depth, "width": width}
            return CreateRectangularSectionResponse(
                dry_run=True, validation_passed=True, would_apply=preview
            )

        sret = sap_model.PropFrame.SetRectangle(name, material, depth, width, color_val, notes, "")
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropFrame.SetRectangle('{name}') returned {ret_code}",
            )
        applied = _read_rectangle(sap_model, name)  # report SAP's actual stored values
        ctx["result_details"] = {"name": name, "material": material,
                                 "depth": applied.depth, "width": applied.width}
        return CreateRectangularSectionResponse(dry_run=False, applied=applied)


def modify_rectangular_section(
    sap_model: Any, oapi_namespace: Any, name: str, material: str | None, depth: float | None,
    width: float | None, color: int | None, notes: str | None, dry_run: bool, confirm: bool
) -> ModifyRectangularSectionResponse:
    """Modify fields of an existing rectangular section, merging with current state.

    Raises OBJECT_NOT_FOUND (unknown), SECTION_TYPE_MISMATCH (not Rectangular),
    NOTHING_TO_MODIFY (no field), CONFIRM_REQUIRED (non-bridge section without confirm),
    INVALID_DIMENSIONS, OBJECT_NOT_FOUND (material).
    """
    with audited(
        "modify_rectangular_section",
        {"name": name, "material": material, "depth": depth, "width": width,
         "color": color, "notes": notes, "dry_run": dry_run, "confirm": confirm},
    ) as ctx:
        # Existence + type.
        sec_type = sections_read.get_section_type(sap_model, oapi_namespace, name)
        if sec_type is None:
            raise SapSessionError(
                error_codes.OBJECT_NOT_FOUND,
                f"section '{name}' does not exist (list with GET /v1/sections)",
            )
        if sec_type != _RECTANGULAR:
            raise SapSessionError(
                error_codes.SECTION_TYPE_MISMATCH,
                f"section '{name}' is type '{sec_type}', not Rectangular; "
                "modify_rectangular_section only handles Rectangular sections",
            )

        if all(v is None for v in (material, depth, width, color, notes)):
            raise SapSessionError(
                error_codes.NOTHING_TO_MODIFY,
                f"modify_rectangular_section('{name}') was given no field to change",
            )

        # Per-field validation of the provided changes.
        if depth is not None:
            _assert_positive("depth", depth)
        if width is not None:
            _assert_positive("width", width)
        if material is not None:
            _assert_material_exists(sap_model, material)

        previous = _read_rectangle(sap_model, name)
        # Merge: new value where provided, current otherwise.
        merged = RectangularSection(
            name=name,
            material=material if material is not None else previous.material,
            depth=depth if depth is not None else previous.depth,
            width=width if width is not None else previous.width,
            color=color if color is not None else previous.color,
            notes=notes if notes is not None else previous.notes,
            section_type=_RECTANGULAR,
        )
        changes = _diff(previous, merged)

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"changes": changes}
            return ModifyRectangularSectionResponse(
                dry_run=True, validation_passed=True,
                would_apply=RectangularSectionChange(current=merged, changes=changes),
            )

        # Modifying a pre-existing (non-bridge) section is destructive → confirm (§5.1).
        if not has_bridge_prefix(name) and not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"section '{name}' is not bridge-owned (no '{get_bridge_prefix()}' prefix); "
                "modifying a pre-existing section requires confirm=true",
            )

        sret = sap_model.PropFrame.SetRectangle(
            name, merged.material, merged.depth, merged.width, merged.color, merged.notes, ""
        )
        ret_code = sret[0] if isinstance(sret, tuple) else sret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED,
                f"PropFrame.SetRectangle('{name}') returned {ret_code}",
            )
        current = _read_rectangle(sap_model, name)
        ctx["result_details"] = {"changes": changes}
        return ModifyRectangularSectionResponse(
            dry_run=False,
            applied=RectangularSectionChange(previous=previous, current=current, changes=changes),
        )


def _diff(old: RectangularSection, new: RectangularSection) -> list[str]:
    """Per-field diff old → new, only for fields that changed."""
    out = []
    for label, ov, nv in (
        ("material", old.material, new.material),
        ("depth", old.depth, new.depth),
        ("width", old.width, new.width),
        ("color", old.color, new.color),
        ("notes", old.notes, new.notes),
    ):
        if ov != nv:
            out.append(f"{label}: {ov} → {nv}")
    return out
