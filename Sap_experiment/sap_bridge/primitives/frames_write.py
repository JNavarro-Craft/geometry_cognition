"""Write-side frame (line) primitives: create / create batch / delete / modify (Fase 1h.2).

Hybrid naming (AI_F### autogen). A frame connects two EXISTING joints — validated before any
create. ``section`` is optional on create: if given it is the AddByPoint PropName; if omitted
SAP assigns its current default section (a frame always has SOME property — "no section" is
reported as whatever SAP stores, read back per M2, never faked).

OAPI notes (brechas §32, §33, verified in pre-flight):
  * FrameObj.AddByPoint(Point1, Point2, Name="", PropName, UserName) → (0, name). Name="" →
    SAP uses UserName. PropName="Default" (or a section name).
  * FrameObj.Delete(Name, eItemType) → 0.
  * Changing endpoints is IN-PLACE: EditFrame.ChangeConnectivity(Name, P1, P2) → 0, and the
    frame's releases SURVIVE the change (§33). So modify_frame needs no delete+recreate.
  * Section (re)assignment: FrameObj.SetSection(Name, PropName, eItemType, 0.0, 0.0).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import error_codes
from ..audit_log import audited
from ..bridge_state import next_frame_name, peek_frame_name
from ..contracts import (
    BatchItemFailure,
    CreateFrameResponse,
    CreateFramesResponse,
    DeleteFrameResponse,
    FrameCreated,
    FrameDeletion,
    FrameModification,
    ModifyFrameResponse,
)
from ..namespace import assert_no_conflict, assert_prefix_required
from ..sap_session import SapSessionError
from . import frames as frames_read
from . import sections as sections_read
from .helpers import apply_batch_atomic, validate_joint_exists

logger = logging.getLogger("sap_bridge.primitives.frames_write")

_DEFAULT_PROP = "Default"


def _resolve_frame_name(state: Any, name: str | None, existing: set[str], consume: bool) -> str:
    if name is not None:
        assert_prefix_required(name)
        assert_no_conflict(name, list(existing))
        return name
    auto = next_frame_name(state) if consume else peek_frame_name(state)
    assert_no_conflict(auto, list(existing))
    return auto


def _validate_section_exists(sap_model: Any, oapi_namespace: Any, section: str) -> None:
    existing = set(sections_read.list_section_names(sap_model, oapi_namespace))
    if section not in existing:
        raise SapSessionError(
            error_codes.OBJECT_NOT_FOUND,
            f"section '{section}' not found (list with GET /v1/sections)",
        )


def _add_frame(sap_model: Any, p_i: str, p_j: str, name: str, prop: str) -> str:
    ret = sap_model.FrameObj.AddByPoint(p_i, p_j, "", prop, name)
    ret_code = ret[0] if isinstance(ret, tuple) else ret
    if ret_code != 0:
        raise SapSessionError(
            error_codes.OAPI_CALL_FAILED,
            f"FrameObj.AddByPoint('{name}', {p_i}->{p_j}) returned {ret_code}",
        )
    assigned = ret[1] if isinstance(ret, tuple) and len(ret) > 1 and ret[1] else name
    return str(assigned)


def create_frame(
    sap_model: Any, oapi_namespace: Any, state: Any, joint_i: str, joint_j: str,
    section: str | None, name: str | None, dry_run: bool, confirm: bool,
) -> CreateFrameResponse:
    """Create one frame between two existing joints. ``section`` optional. confirm mandatory."""
    with audited("create_frame", {"joint_i": joint_i, "joint_j": joint_j, "section": section,
                                  "name": name, "dry_run": dry_run, "confirm": confirm}) as ctx:
        validate_joint_exists(sap_model, joint_i)
        validate_joint_exists(sap_model, joint_j)
        if section is not None:
            _validate_section_exists(sap_model, oapi_namespace, section)
        existing = set(frames_read.list_frame_names(sap_model))

        if dry_run:
            final = _resolve_frame_name(state, name, existing, consume=False)
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": final, "i": joint_i, "j": joint_j, "section": section}
            return CreateFrameResponse(
                dry_run=True,
                would_apply=FrameCreated(name=final, point_i=joint_i, point_j=joint_j,
                                         section=section or ""),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                "create_frame modifies the model; pass confirm=true to create",
            )

        final = _resolve_frame_name(state, name, existing, consume=True)
        prop = section if section is not None else _DEFAULT_PROP
        assigned = _add_frame(sap_model, joint_i, joint_j, final, prop)
        stored_section = frames_read.get_frame_section(sap_model, assigned)  # M2
        ctx["result_details"] = {"name": assigned, "section": stored_section}
        return CreateFrameResponse(
            dry_run=False,
            applied=FrameCreated(name=assigned, point_i=joint_i, point_j=joint_j,
                                 section=stored_section),
        )


def create_frames(
    sap_model: Any, oapi_namespace: Any, state: Any, frames: list[dict], dry_run: bool, confirm: bool,
) -> CreateFramesResponse:
    """Create many frames atomically (stop-on-first-failure)."""
    with audited("create_frames", {"count": len(frames), "dry_run": dry_run, "confirm": confirm}) as ctx:
        if not frames:
            raise SapSessionError(error_codes.EMPTY_BATCH, "create_frames: the batch is empty")

        # Strict pre-validation: every joint and every referenced section must exist; resolve
        # all names against a growing set.
        existing = set(frames_read.list_frame_names(sap_model))
        resolved: list[tuple[FrameCreated, str]] = []  # (record, prop to pass to AddByPoint)
        for spec in frames:
            validate_joint_exists(sap_model, spec["joint_i"])
            validate_joint_exists(sap_model, spec["joint_j"])
            sec = spec.get("section")
            if sec is not None:
                _validate_section_exists(sap_model, oapi_namespace, sec)
            final = _resolve_frame_name(state, spec.get("name"), existing, consume=not dry_run)
            existing.add(final)
            resolved.append((
                FrameCreated(name=final, point_i=spec["joint_i"], point_j=spec["joint_j"],
                             section=sec or ""),
                sec if sec is not None else _DEFAULT_PROP,
            ))

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"count": len(resolved)}
            return CreateFramesResponse(
                dry_run=True, count=len(resolved), would_apply=[r for r, _p in resolved]
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"create_frames creates {len(frames)} frame(s); pass confirm=true to apply",
            )

        def _apply(_idx: int, item: tuple[FrameCreated, str]) -> FrameCreated:
            rec, prop = item
            assigned = _add_frame(sap_model, rec.point_i, rec.point_j, rec.name, prop)
            stored = frames_read.get_frame_section(sap_model, assigned)  # M2
            return FrameCreated(name=assigned, point_i=rec.point_i, point_j=rec.point_j,
                                section=stored)

        outcome = apply_batch_atomic(resolved, _apply)
        failed = None
        not_attempted = None
        if outcome.failed_index is not None:
            rec, _p = outcome.failed_item
            failed = BatchItemFailure(
                index=outcome.failed_index,
                item=f"frame '{rec.name}' ({rec.point_i}->{rec.point_j})",
                reason=outcome.failed_reason or "unknown",
            )
            not_attempted = [r.name for r, _p in outcome.not_attempted]
        ctx["result"] = "applied" if failed is None else f"error_{error_codes.OAPI_CALL_FAILED}"
        ctx["result_details"] = {"applied_count": len(outcome.applied),
                                 "failed_at": failed.index if failed else None}
        return CreateFramesResponse(
            dry_run=False, count=len(resolved), applied=outcome.applied,
            failed_at=failed, not_attempted=not_attempted,
        )


def delete_frame(
    sap_model: Any, name: str, dry_run: bool, confirm: bool,
) -> DeleteFrameResponse:
    """Delete a frame. No cascade constraints (a frame has no sub-objects). confirm mandatory."""
    with audited("delete_frame", {"name": name, "dry_run": dry_run, "confirm": confirm}) as ctx:
        if name not in set(frames_read.list_frame_names(sap_model)):
            raise SapSessionError(error_codes.OBJECT_NOT_FOUND, f"frame '{name}' not found")
        pret, p_i, p_j = sap_model.FrameObj.GetPoints(name, "", "")
        if pret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED, f"FrameObj.GetPoints('{name}') returned {pret}"
            )

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": name, "i": str(p_i), "j": str(p_j)}
            return DeleteFrameResponse(
                dry_run=True,
                would_apply=FrameDeletion(name=name, point_i=str(p_i), point_j=str(p_j)),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"delete_frame removes frame '{name}'; pass confirm=true to delete",
            )

        from ..sap_session import get_session
        item_objects = get_session().oapi_namespace().eItemType.Objects
        ret = sap_model.FrameObj.Delete(name, item_objects)
        ret_code = ret[0] if isinstance(ret, tuple) else ret
        if ret_code != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED, f"FrameObj.Delete('{name}') returned {ret_code}"
            )
        ctx["result_details"] = {"name": name}
        return DeleteFrameResponse(
            dry_run=False, applied=FrameDeletion(name=name, point_i=str(p_i), point_j=str(p_j))
        )


def modify_frame(
    sap_model: Any, oapi_namespace: Any, name: str, joint_i: str | None, joint_j: str | None,
    section: str | None, dry_run: bool, confirm: bool,
) -> ModifyFrameResponse:
    """Modify a frame's endpoints and/or section. Endpoints change IN-PLACE via
    ChangeConnectivity (§33, releases preserved). ``section=''`` is treated as a request to set
    the default section (SAP has no true "no section"). At least one field must be given."""
    with audited("modify_frame", {"name": name, "joint_i": joint_i, "joint_j": joint_j,
                                  "section": section, "dry_run": dry_run, "confirm": confirm}) as ctx:
        if joint_i is None and joint_j is None and section is None:
            raise SapSessionError(
                error_codes.NOTHING_TO_MODIFY,
                "modify_frame: provide at least one of joint_i_name / joint_j_name / section",
            )
        if name not in set(frames_read.list_frame_names(sap_model)):
            raise SapSessionError(error_codes.OBJECT_NOT_FOUND, f"frame '{name}' not found")

        pret, cur_i, cur_j = sap_model.FrameObj.GetPoints(name, "", "")
        if pret != 0:
            raise SapSessionError(
                error_codes.OAPI_CALL_FAILED, f"FrameObj.GetPoints('{name}') returned {pret}"
            )
        cur_i, cur_j = str(cur_i), str(cur_j)
        cur_section = frames_read.get_frame_section(sap_model, name)

        # Validate the new references before touching anything.
        if joint_i is not None:
            validate_joint_exists(sap_model, joint_i)
        if joint_j is not None:
            validate_joint_exists(sap_model, joint_j)
        if section is not None and section != "":
            _validate_section_exists(sap_model, oapi_namespace, section)

        new_i = joint_i if joint_i is not None else cur_i
        new_j = joint_j if joint_j is not None else cur_j
        new_section = section if section is not None else cur_section
        changes = []
        if joint_i is not None and joint_i != cur_i:
            changes.append(f"point_i: {cur_i} → {joint_i}")
        if joint_j is not None and joint_j != cur_j:
            changes.append(f"point_j: {cur_j} → {joint_j}")
        if section is not None and section != cur_section:
            changes.append(f"section: {cur_section} → {section or _DEFAULT_PROP}")

        if dry_run:
            ctx["result"] = "preview_only"
            ctx["result_details"] = {"name": name, "changes": changes}
            return ModifyFrameResponse(
                dry_run=True,
                would_apply=FrameModification(
                    name=name, previous_point_i=cur_i, previous_point_j=cur_j,
                    previous_section=cur_section, current_point_i=new_i, current_point_j=new_j,
                    current_section=new_section, changes=changes,
                ),
            )

        if not confirm:
            raise SapSessionError(
                error_codes.CONFIRM_REQUIRED,
                f"modify_frame changes frame '{name}'; pass confirm=true to apply",
            )

        # Endpoints in-place (preserves releases, §33).
        if (joint_i is not None and joint_i != cur_i) or (joint_j is not None and joint_j != cur_j):
            cret = sap_model.EditFrame.ChangeConnectivity(name, new_i, new_j)
            cret_code = cret[0] if isinstance(cret, tuple) else cret
            if cret_code != 0:
                raise SapSessionError(
                    error_codes.OAPI_CALL_FAILED,
                    f"EditFrame.ChangeConnectivity('{name}') returned {cret_code}",
                )
        # Section reassignment.
        if section is not None and section != cur_section:
            prop = section if section != "" else _DEFAULT_PROP
            item_objects = oapi_namespace.eItemType.Objects
            sret = sap_model.FrameObj.SetSection(name, prop, item_objects, 0.0, 0.0)
            sret_code = sret[0] if isinstance(sret, tuple) else sret
            if sret_code != 0:
                raise SapSessionError(
                    error_codes.OAPI_CALL_FAILED,
                    f"FrameObj.SetSection('{name}', '{prop}') returned {sret_code}",
                )

        # Read back the final state (M2).
        _r, f_i, f_j = sap_model.FrameObj.GetPoints(name, "", "")
        f_section = frames_read.get_frame_section(sap_model, name)
        ctx["result_details"] = {"name": name, "changes": changes}
        return ModifyFrameResponse(
            dry_run=False,
            applied=FrameModification(
                name=name, previous_point_i=cur_i, previous_point_j=cur_j,
                previous_section=cur_section, current_point_i=str(f_i), current_point_j=str(f_j),
                current_section=f_section, changes=changes,
            ),
        )
