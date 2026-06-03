"""FastAPI app for the SAP bridge — the single HTTP integration point with SAP2000.

Runs on localhost:8766 (geometry_cognition's Rhino bridge uses 8765; SAP gets 8766).
Endpoints are versioned under /v1 and every failure returns a structured
ErrorResponse so all consumers — MCP, Rhino plugins, scripts — branch on a stable
code. Read endpoints are GET; the one mutating operation (running analysis) is POST,
signalling intent to the consumer. This module wires routes to the primitives; it
holds no domain logic.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from . import error_codes
from .contracts import (
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisStatusResponse,
    CombinationsResponse,
    DistributedLoadsResponse,
    ErrorResponse,
    FrameForcesResponse,
    FramesResponse,
    HealthResponse,
    JointDisplacementsResponse,
    JointReactionsResponse,
    JointsResponse,
    LoadCaseDetailsResponse,
    LoadCasesResponse,
    LoadPatternsResponse,
    CreateLoadPatternRequest,
    CreateLoadPatternResponse,
    MaterialsResponse,
    CreateJointRequest,
    CreateJointResponse,
    CreateJointsRequest,
    CreateJointsResponse,
    DeleteJointRequest,
    DeleteJointResponse,
    ModifyJointRequest,
    ModifyJointResponse,
    SetJointRestraintsRequest,
    SetJointRestraintsResponse,
    SetJointRestraintsBatchRequest,
    SetJointRestraintsBatchResponse,
    JointRestraintsResponse,
    AssignJointLoadRequest,
    AssignJointLoadResponse,
    AssignJointLoadsBatchRequest,
    AssignJointLoadsBatchResponse,
    ClearJointLoadsRequest,
    ClearJointLoadsResponse,
    JointLoadsResponse,
    AssignFrameLoadDistributedRequest,
    AssignFrameLoadDistributedResponse,
    AssignFrameLoadsDistributedBatchRequest,
    AssignFrameLoadsDistributedBatchResponse,
    AssignFrameLoadPointRequest,
    AssignFrameLoadPointResponse,
    AssignFrameLoadsPointBatchRequest,
    AssignFrameLoadsPointBatchResponse,
    CreateFrameRequest,
    CreateFrameResponse,
    CreateFramesRequest,
    CreateFramesResponse,
    DeleteFrameRequest,
    DeleteFrameResponse,
    ModifyFrameRequest,
    ModifyFrameResponse,
    SetFrameReleasesRequest,
    SetFrameReleasesResponse,
    ModelSettingsResponse,
    NewBlankModelRequest,
    NewBlankModelResponse,
    OpenModelRequest,
    OpenModelResponse,
    PointLoadsResponse,
    ResetWorkspaceRequest,
    ResetWorkspaceResponse,
    SaveWorkspaceAsRequest,
    SaveWorkspaceAsResponse,
    SetModelLockedRequest,
    SetModelLockedResponse,
    SavepointCreateRequest,
    SavepointCreateResponse,
    SavepointListResponse,
    SavepointRestoreRequest,
    SavepointRestoreResponse,
    CreateMaterialRequest,
    CreateMaterialResponse,
    AssignBatchRequest,
    AssignmentResponse,
    AssignToFramesRequest,
    CreateRectangularSectionRequest,
    CreateRectangularSectionResponse,
    ModifyRectangularSectionRequest,
    ModifyRectangularSectionResponse,
    SectionPropertiesResponse,
    SectionsResponse,
    SetActiveDOFRequest,
    SetActiveDOFResponse,
    SetMaterialPropertiesIsotropicRequest,
    SetMaterialPropertiesIsotropicResponse,
    SetPresentUnitsRequest,
    SetPresentUnitsResponse,
    UnitsResponse,
)
from .path_resolver import resolve_oapi_dll
from .primitives import active_dof as active_dof_primitive
from .primitives import analysis as analysis_primitive
from .primitives import combinations as combinations_primitive
from .primitives import frame_loads as frame_loads_primitive
from .primitives import frame_results as frame_results_primitive
from .primitives import frames as frames_primitive
from .primitives import joint_loads as joint_loads_primitive
from .primitives import joint_results as joint_results_primitive
from .primitives import joints as joints_primitive
from .primitives import load_case_details as load_case_details_primitive
from .primitives import load_cases as load_cases_primitive
from .primitives import load_patterns as load_patterns_primitive
from .primitives import materials as materials_primitive
from .primitives import materials_write as materials_write_primitive
from .primitives import frames_write as frames_write_primitive
from .primitives import joints_write as joints_write_primitive
from .primitives import model_initialization as model_initialization_primitive
from .primitives import persistence as persistence_primitive
from .primitives import model_settings as model_settings_primitive
from .primitives import model_state as model_state_primitive
from .primitives import present_units as present_units_primitive
from .primitives import savepoints as savepoints_primitive
from .primitives import section_assignment as section_assignment_primitive
from .primitives import section_properties as section_properties_primitive
from .primitives import sections as sections_primitive
from .primitives import sections_write as sections_write_primitive
from .primitives import workspace as workspace_primitive
from .primitives import units as units_primitive
from .sap_session import SapSessionError, get_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("sap_bridge")

app = FastAPI(
    title="SAP Bridge",
    version="0.1.0",
    description="Read-only HTTP bridge to a running SAP2000 OAPI session. "
    "Exposes facts (coordinates, connectivity, properties); interprets nothing.",
)


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(code=code, message=message)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(SapSessionError)
async def _session_error_handler(_request, exc: SapSessionError) -> JSONResponse:
    """Map session/transport failures to the structured error envelope.

    'Not attached / not running / no model' are client-fixable preconditions (409).
    Everything else (OAPI failure, bad shape, missing assembly) is 502: the bridge
    reached for SAP and something on that side went wrong.
    """
    precondition = {
        error_codes.SESSION_NOT_ATTACHED,
        error_codes.SAP_NOT_RUNNING,
        error_codes.SAP_PROCESS_DIED,
        error_codes.NO_MODEL_OPEN,
        error_codes.CASE_NOT_RUN,
        # Write-side preconditions — all client-fixable (fix the request and retry).
        error_codes.CONFIRM_REQUIRED,
        error_codes.PREFIX_REQUIRED,
        error_codes.NAME_ALREADY_EXISTS,
        error_codes.OBJECT_NOT_FOUND,
        error_codes.DRY_RUN_VALIDATION_FAILED,
        error_codes.SAVEPOINT_NOT_FOUND,
        error_codes.SAVEPOINT_ALREADY_EXISTS,
        error_codes.UNKNOWN_UNIT_SYSTEM,
        error_codes.UNKNOWN_MATERIAL_TYPE,
        error_codes.INVALID_DIMENSIONS,
        error_codes.SECTION_TYPE_MISMATCH,
        error_codes.NOTHING_TO_MODIFY,
        error_codes.EMPTY_BATCH,
        error_codes.FILE_NOT_FOUND,
        error_codes.INVALID_PATH,
        error_codes.EMPTY_MODEL,
        error_codes.JOINT_HAS_CONNECTED_FRAMES,
        error_codes.UNKNOWN_LOAD_PATTERN_TYPE,
        error_codes.UNKNOWN_LOAD_DIRECTION,
    }
    status = 409 if exc.code in precondition else 502
    logger.warning("session error [%s]: %s", exc.code, exc.message)
    return _error(exc.code, exc.message, status)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness of the bridge process plus whether a SAP session is currently attached.
    Does not attach; safe to poll. Mirrors geometry_cognition's /health."""
    session = get_session()
    return HealthResponse(
        status="ok",
        sap_attached=session.is_alive(),
        oapi_dll=resolve_oapi_dll(),
    )


@app.get("/v1/units", response_model=UnitsResponse)
def get_units() -> UnitsResponse:
    """Active SAP2000 unit system as a fact. The bridge never converts units; the
    client converts knowing what it holds on each side."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return units_primitive.get_present_units(model)


@app.get("/v1/model/settings", response_model=ModelSettingsResponse)
def get_model_settings() -> ModelSettingsResponse:
    """Model configuration facts: active_dof [U1,U2,U3,R1,R2,R3], model_is_locked, and
    present + database units. The bridge does not interpret the DOF vector — it never
    labels a model 'Plane Frame' or '2D'; the client recognises that from the flags."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return ModelSettingsResponse(settings=model_settings_primitive.get_model_settings(model))


@app.post("/v1/model/settings/active_dof", response_model=SetActiveDOFResponse)
def set_active_dof(request: SetActiveDOFRequest) -> SetActiveDOFResponse:
    """Set the model's active DOFs (write — global setting). ``active_dof`` must be exactly
    6 booleans [U1,U2,U3,R1,R2,R3]. ``confirm`` is mandatory (else confirm_required);
    ``dry_run`` previews the change with a per-DOF diff without applying. The bridge
    validates shape only and relays SAP — it does not judge the pattern or auto-unlock a
    locked model (a locked model rejects the change → oapi_call_failed)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return active_dof_primitive.set_active_dof(
            model, session.oapi_namespace(), request.active_dof, request.dry_run, request.confirm
        )


@app.post("/v1/model/settings/present_units", response_model=SetPresentUnitsResponse)
def set_present_units(request: SetPresentUnitsRequest) -> SetPresentUnitsResponse:
    """Set the model's present (display) units by name (write — global setting). ``units``
    is an eUnits member name (e.g. 'N_m_C'); an unknown name → unknown_unit_system.
    ``confirm`` is mandatory (else confirm_required); ``dry_run`` previews. Changing present
    units reformats how the read-side reports values (a display preference, not a data
    conversion); database_units is not touched. model_is_locked is unaffected."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return present_units_primitive.set_present_units(
            model, session.oapi_namespace(), request.units, request.dry_run, request.confirm
        )


@app.post("/v1/model/locked", response_model=SetModelLockedResponse)
def set_model_locked(request: SetModelLockedRequest) -> SetModelLockedResponse:
    """Set the model lock state (write — global state). ``confirm`` mandatory (else
    confirm_required); ``dry_run`` previews; idempotent. run_analysis locks the model and SAP
    rejects edits while locked — call this with locked=false to keep modifying. The bridge
    does NOT auto-unlock on other writes."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return model_state_primitive.set_model_locked(
            model, request.locked, request.dry_run, request.confirm
        )


@app.post("/v1/model/open", response_model=OpenModelResponse)
def open_model(request: OpenModelRequest) -> OpenModelResponse:
    """Open a model, replacing the loaded one (write). ``path`` must be an absolute .sdb that
    exists (else invalid_path / file_not_found — checked before OpenFile so SAP never lands on
    a phantom path). ``confirm`` mandatory (discards unsaved changes); ``dry_run`` previews.
    The opened model becomes the new base: the bridge re-anchors to a fresh workspace derived
    from it. Useful to recover the base model after a restore."""
    session = get_session()
    with session.lock():
        session.sap_model()  # ensure attached
        return model_state_primitive.open_model(
            session.sap_model, session.workspace, request.path, request.dry_run, request.confirm
        )


@app.post("/v1/model/new_blank", response_model=NewBlankModelResponse)
def new_blank_model(request: NewBlankModelRequest) -> NewBlankModelResponse:
    """Initialize an empty model from scratch (write — build-from-blank, Fase 1h.1). ``units``
    is an eUnits member NAME (else unknown_unit_system). DESTRUCTIVE: discards the currently
    loaded model WITHOUT saving → ``confirm`` mandatory (else confirm_required); ``dry_run``
    previews. The empty model gets a temp workspace (no base file); build it with the create_*
    primitives, then save_workspace_as to materialize it as a new base. Units are not anchored
    (set_present_units can change them)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()  # ensure attached
        return model_initialization_primitive.new_blank_model(
            model, session.oapi_namespace(), session.workspace,
            request.units, request.dry_run, request.confirm,
        )


@app.post("/v1/workspace/reset", response_model=ResetWorkspaceResponse)
def reset_workspace(request: ResetWorkspaceRequest) -> ResetWorkspaceResponse:
    """Reset the transient workspace to a clean copy of the immutable base model (write). The
    base file is only read, never written. ``confirm`` mandatory (discards workspace edits);
    ``dry_run`` previews. Use this to return to a known baseline between iterations without
    relying on savepoints."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return workspace_primitive.reset_workspace(
            model, session.workspace, request.dry_run, request.confirm
        )


@app.post("/v1/workspace/save_as", response_model=SaveWorkspaceAsResponse)
def save_workspace_as(request: SaveWorkspaceAsRequest) -> SaveWorkspaceAsResponse:
    """Save the current workspace content to ``path`` as a NEW base model (write — closes the
    build-from-blank cycle). ``path`` must be absolute .sdb and must NOT be the current base
    (that is a future commit_workspace_to_base; else invalid_path). ``confirm`` is mandatory
    only to OVERWRITE an existing file; ``dry_run`` previews. After saving, ``path`` becomes
    the immutable base and the bridge re-anchors onto a fresh workspace beside it."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return persistence_primitive.save_workspace_as(
            model, session.workspace, request.path, request.dry_run, request.confirm
        )


@app.get("/v1/joints", response_model=JointsResponse)
def get_joints() -> JointsResponse:
    """Every point object: name, global Cartesian coordinates (in the present units,
    echoed in ``units``) and the raw 6-DOF restraint flags. No domain naming."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = joints_primitive.get_joints(model)
        return JointsResponse(units=present_units, count=len(rows), joints=rows)


@app.post("/v1/joints", response_model=CreateJointResponse)
def create_joint(request: CreateJointRequest) -> CreateJointResponse:
    """Create one joint at (x,y,z) in present units (write — geometry, Fase 1h.2). ``name``
    optional: prefix-enforced if given, autogenerated AI_J### if omitted. ``confirm`` mandatory
    (modifies the model); ``dry_run`` previews the resolved name + coords."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.create_joint(
            model, session.workspace, request.x, request.y, request.z,
            request.name, request.dry_run, request.confirm,
        )


@app.post("/v1/joints/batch", response_model=CreateJointsResponse)
def create_joints(request: CreateJointsRequest) -> CreateJointsResponse:
    """Create many joints atomically (write — stop-on-first-failure). Autogen names resolve in
    order; ``dry_run`` previews ALL resolved names. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.create_joints(
            model, session.workspace, [j.model_dump() for j in request.joints],
            request.dry_run, request.confirm,
        )


@app.delete("/v1/joints/{name}", response_model=DeleteJointResponse)
def delete_joint(name: str, request: DeleteJointRequest) -> DeleteJointResponse:
    """Delete a joint (write — destructive). Refused with joint_has_connected_frames if any
    frame touches it (delete those first). ``confirm`` mandatory; ``dry_run`` reports whether
    it has connected frames."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.delete_joint(
            model, name, request.dry_run, request.confirm
        )


@app.patch("/v1/joints/{name}", response_model=ModifyJointResponse)
def modify_joint(name: str, request: ModifyJointRequest) -> ModifyJointResponse:
    """Move a joint to new coords (write). Affects every connected frame → ``confirm``
    mandatory; ``dry_run`` previews old/new coords + the affected frames."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.modify_joint(
            model, name, request.x, request.y, request.z, request.dry_run, request.confirm
        )


@app.get("/v1/joints/{name}/restraints", response_model=JointRestraintsResponse)
def get_joint_restraints(name: str) -> JointRestraintsResponse:
    """The 6-DOF restraint flags [U1,U2,U3,R1,R2,R3] of one joint (read). true = restrained.
    Facts only — no pinned/fixed/roller classification (that is your domain reasoning)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        from .contracts import RestraintFlags
        flags = joints_primitive.get_joint_restraints(model, name)
        return JointRestraintsResponse(
            name=name,
            restraints=RestraintFlags(**{d: flags[i] for i, d in enumerate(
                ("U1", "U2", "U3", "R1", "R2", "R3"))}),
        )


@app.post("/v1/joints/{name}/restraints", response_model=SetJointRestraintsResponse)
def set_joint_restraints(name: str, request: SetJointRestraintsRequest) -> SetJointRestraintsResponse:
    """Set a joint's 6-DOF restraints (write — boundary condition). ``restraints`` are named flags
    [U1,U2,U3,R1,R2,R3], true = restrained; omitted = False; SetRestraint overwrites the whole
    state. ``confirm`` mandatory; ``dry_run`` previews vs current. No domain naming — the client
    composes pinned/fixed/roller from the flags."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.set_joint_restraints(
            model, session.oapi_namespace(), name, request.restraints.model_dump(),
            request.dry_run, request.confirm,
        )


@app.post("/v1/joints/restraints/batch", response_model=SetJointRestraintsBatchResponse)
def set_joint_restraints_batch(request: SetJointRestraintsBatchRequest) -> SetJointRestraintsBatchResponse:
    """Set restraints on many joints atomically (write — stop-on-first-failure). Each {name,
    restraints}. All joints validated up front. ``confirm`` mandatory; ``dry_run`` previews."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joints_write_primitive.set_joint_restraints_batch(
            model, session.oapi_namespace(),
            [{"name": it.name, "restraints": it.restraints.model_dump()} for it in request.items],
            request.dry_run, request.confirm,
        )


@app.get("/v1/joints/{name}/loads", response_model=JointLoadsResponse)
def get_joint_loads(name: str) -> JointLoadsResponse:
    """All loads on one joint (read — Fase 1h.4), one entry per pattern: pattern, the 6
    components {F1..M3} and coord_sys. Empty if none. (See also /loads/point for the 1c.2 shape.)"""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joint_loads_primitive.get_joint_loads(model, name)


@app.post("/v1/joints/{name}/loads", response_model=AssignJointLoadResponse)
def assign_joint_load(name: str, request: AssignJointLoadRequest) -> AssignJointLoadResponse:
    """Assign a point load to a joint (write — ACCUMULATES). ``forces``/``moments`` named (default
    0); ``coord_sys`` Global/Local. Validates joint + pattern exist. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joint_loads_primitive.assign_joint_load(
            model, name, request.pattern_name, request.forces.model_dump(),
            request.moments.model_dump(), request.coord_sys, request.dry_run, request.confirm,
        )


@app.post("/v1/joints/loads/batch", response_model=AssignJointLoadsBatchResponse)
def assign_joint_loads_batch(request: AssignJointLoadsBatchRequest) -> AssignJointLoadsBatchResponse:
    """Assign point loads to many joints atomically (write — stop-on-first-failure). Each
    {joint_name, pattern_name, forces?, moments?, coord_sys?}. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        items = [{"joint_name": it.joint_name, "pattern_name": it.pattern_name,
                  "forces": it.forces.model_dump(), "moments": it.moments.model_dump(),
                  "coord_sys": it.coord_sys} for it in request.items]
        return joint_loads_primitive.assign_joint_loads_batch(
            model, items, request.dry_run, request.confirm)


@app.delete("/v1/joints/{name}/loads", response_model=ClearJointLoadsResponse)
def clear_joint_loads(name: str, request: ClearJointLoadsRequest) -> ClearJointLoadsResponse:
    """Clear loads on a joint (write — destructive). ``pattern_name`` given = only that pattern;
    omitted/null = ALL patterns. ``confirm`` mandatory; ``dry_run`` reports how many would clear."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return joint_loads_primitive.clear_joint_loads(
            model, name, request.pattern_name, request.dry_run, request.confirm)


@app.get("/v1/frames", response_model=FramesResponse)
def get_frames() -> FramesResponse:
    """Every frame object: name, the two end point names (connectivity, matching
    joint names) and the assigned section property. Facts only — no structural role
    classification (chord/strut/diagonal is your domain reasoning)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = frames_primitive.get_frames(model)
        return FramesResponse(units=present_units, count=len(rows), frames=rows)


@app.post("/v1/frames", response_model=CreateFrameResponse)
def create_frame(request: CreateFrameRequest) -> CreateFrameResponse:
    """Create one frame between two EXISTING joints (write — geometry). ``section`` optional
    (validated if given); ``name`` optional (autogen AI_F###). Both joints validated before
    create (else object_not_found). ``confirm`` mandatory; ``dry_run`` previews."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frames_write_primitive.create_frame(
            model, session.oapi_namespace(), session.workspace,
            request.joint_i_name, request.joint_j_name, request.section,
            request.name, request.dry_run, request.confirm,
        )


@app.post("/v1/frames/batch", response_model=CreateFramesResponse)
def create_frames(request: CreateFramesRequest) -> CreateFramesResponse:
    """Create many frames atomically (write — stop-on-first-failure). Each {joint_i, joint_j,
    section?, name?}. All joints/sections validated up front; ``dry_run`` previews resolved
    names. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frames_write_primitive.create_frames(
            model, session.oapi_namespace(), session.workspace,
            [f.model_dump() for f in request.frames], request.dry_run, request.confirm,
        )


@app.delete("/v1/frames/{name}", response_model=DeleteFrameResponse)
def delete_frame(name: str, request: DeleteFrameRequest) -> DeleteFrameResponse:
    """Delete a frame (write — destructive). No cascade constraints. ``confirm`` mandatory;
    ``dry_run`` confirms the frame exists and reports its endpoints."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frames_write_primitive.delete_frame(
            model, name, request.dry_run, request.confirm
        )


@app.patch("/v1/frames/{name}", response_model=ModifyFrameResponse)
def modify_frame(name: str, request: ModifyFrameRequest) -> ModifyFrameResponse:
    """Modify a frame's endpoints and/or section (write). Endpoints change in-place
    (ChangeConnectivity — releases preserved, §33). At least one field required (else
    nothing_to_modify). ``confirm`` mandatory; ``dry_run`` previews the changes."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frames_write_primitive.modify_frame(
            model, session.oapi_namespace(), name, request.joint_i_name, request.joint_j_name,
            request.section, request.dry_run, request.confirm,
        )


@app.post("/v1/frames/{name}/releases", response_model=SetFrameReleasesResponse)
def set_frame_releases(name: str, request: SetFrameReleasesRequest) -> SetFrameReleasesResponse:
    """Set a frame's 6-DOF end releases (write). ``releases_i``/``releases_j`` are named flags
    [U1,U2,U3,R1,R2,R3], true = released. ``confirm`` mandatory; ``dry_run`` previews vs current.
    SAP may reject an unstable combination → oapi_call_failed (not reinterpreted)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frames_write_primitive.set_frame_releases(
            model, session.oapi_namespace(), name,
            request.releases_i.model_dump(), request.releases_j.model_dump(),
            request.dry_run, request.confirm,
        )


@app.get("/v1/frames/{name}/loads/distributed", response_model=DistributedLoadsResponse)
def get_distributed_loads_on_frame(name: str) -> DistributedLoadsResponse:
    """Distributed loads on ONE frame (by exact name, as in /v1/frames), across all load
    patterns. Each load reports pattern, type, direction (name + raw code), coord system,
    relative extents and values (present units). Empty list if the frame has none — not
    an error. Direction is relayed raw ('Gravity' stays 'Gravity')."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = frame_loads_primitive.get_distributed_loads_on_frame(
            model, session.oapi_namespace(), name
        )
        return DistributedLoadsResponse(
            units=present_units, frame=name, count=len(rows), loads=rows
        )


@app.post("/v1/frames/{name}/loads/distributed", response_model=AssignFrameLoadDistributedResponse)
def assign_frame_load_distributed(name: str, request: AssignFrameLoadDistributedRequest) -> AssignFrameLoadDistributedResponse:
    """Assign a uniform distributed load to a frame (write — ACCUMULATES). ``value`` over 0%-100%;
    ``direction`` (Local1/2/3, X/Y/Z, XProj.., Gravity, GravityProj — §35); ``coord_sys`` (forced
    for some directions); ``load_type`` Force/Moment. Validates frame + pattern. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frame_loads_primitive.assign_frame_load_distributed(
            model, name, request.pattern_name, request.value, request.direction,
            request.coord_sys, request.load_type, request.dry_run, request.confirm,
        )


@app.post("/v1/frames/loads/distributed/batch", response_model=AssignFrameLoadsDistributedBatchResponse)
def assign_frame_loads_distributed_batch(request: AssignFrameLoadsDistributedBatchRequest) -> AssignFrameLoadsDistributedBatchResponse:
    """Assign uniform distributed loads to many frames atomically (write — stop-on-first-failure).
    Each {frame_name, pattern_name, value, direction, coord_sys?, load_type?}. ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        items = [{"frame_name": it.frame_name, "pattern_name": it.pattern_name, "value": it.value,
                  "direction": it.direction, "coord_sys": it.coord_sys, "load_type": it.load_type}
                 for it in request.items]
        return frame_loads_primitive.assign_frame_load_distributed_batch(
            model, items, request.dry_run, request.confirm)


@app.post("/v1/frames/{name}/loads/point", response_model=AssignFrameLoadPointResponse)
def assign_frame_load_point(name: str, request: AssignFrameLoadPointRequest) -> AssignFrameLoadPointResponse:
    """Assign a point load to a frame at ``distance`` (write — ACCUMULATES). ``rel_distance`` True =
    0..1 relative, False = absolute. ``direction``/``coord_sys``/``load_type`` as in distributed
    (§35). Validates frame + pattern. ``confirm`` mandatory; ``dry_run`` previews."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return frame_loads_primitive.assign_frame_load_point(
            model, name, request.pattern_name, request.value, request.distance, request.direction,
            request.rel_distance, request.coord_sys, request.load_type, request.dry_run, request.confirm,
        )


@app.post("/v1/frames/loads/point/batch", response_model=AssignFrameLoadsPointBatchResponse)
def assign_frame_loads_point_batch(request: AssignFrameLoadsPointBatchRequest) -> AssignFrameLoadsPointBatchResponse:
    """Assign point loads to many frames atomically (write — stop-on-first-failure). Each
    {frame_name, pattern_name, value, distance, direction, rel_distance?, coord_sys?, load_type?}.
    ``confirm`` mandatory."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        items = [{"frame_name": it.frame_name, "pattern_name": it.pattern_name, "value": it.value,
                  "distance": it.distance, "direction": it.direction, "rel_distance": it.rel_distance,
                  "coord_sys": it.coord_sys, "load_type": it.load_type} for it in request.items]
        return frame_loads_primitive.assign_frame_load_point_batch(
            model, items, request.dry_run, request.confirm)


@app.get("/v1/joints/{name}/loads/point", response_model=PointLoadsResponse)
def get_point_loads_on_joint(name: str) -> PointLoadsResponse:
    """Point loads (force + moment) on ONE joint (by exact name, as in /v1/joints),
    across all load patterns. Each reports pattern, coord system and the six F/M
    components (present units). Empty list if the joint has none — not an error."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = joint_loads_primitive.get_point_loads_on_joint(
            model, session.oapi_namespace(), name
        )
        return PointLoadsResponse(
            units=present_units, joint=name, count=len(rows), loads=rows
        )


@app.get("/v1/sections", response_model=SectionsResponse)
def get_sections() -> SectionsResponse:
    """The frame section property catalogue defined in the model: name + SAP type.
    Names are model-supplied labels relayed verbatim; the bridge does not interpret
    them or resolve their dimensions here."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = sections_primitive.get_sections(model, session.oapi_namespace())
        return SectionsResponse(units=present_units, count=len(rows), sections=rows)


@app.get("/v1/sections/{name}/properties", response_model=SectionPropertiesResponse)
def get_section_properties(name: str) -> SectionPropertiesResponse:
    """Dimensions + universal section properties for ONE frame section (by exact name,
    as returned by /v1/sections). Dimension keys are SAP's own parameter names; the
    bridge does not normalize across shapes. Unsupported shapes return
    oapi_unexpected_shape carrying the received type. Values are in present units."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        section = section_properties_primitive.get_section_properties(
            model, session.oapi_namespace(), name
        )
        return SectionPropertiesResponse(units=present_units, section=section)


@app.post("/v1/sections", response_model=CreateRectangularSectionResponse)
def create_rectangular_section(
    request: CreateRectangularSectionRequest,
) -> CreateRectangularSectionResponse:
    """Create a rectangular section (write — new object). ``name`` must carry the bridge
    prefix (else prefix_required); ``material`` must exist (else object_not_found);
    ``depth``/``width`` must be > 0 (else invalid_dimensions). An existing name →
    name_already_exists (SAP would otherwise overwrite silently). No confirm. ``dry_run``
    previews. Values read back from SAP after creation."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return sections_write_primitive.create_rectangular_section(
            model, session.oapi_namespace(), request.name, request.material, request.depth,
            request.width, request.color, request.notes, request.dry_run,
        )


@app.patch("/v1/sections/{name}", response_model=ModifyRectangularSectionResponse)
def modify_rectangular_section(
    name: str, request: ModifyRectangularSectionRequest
) -> ModifyRectangularSectionResponse:
    """Modify a rectangular section (write). The section must exist and be Rectangular
    (else object_not_found / section_type_mismatch). Only provided fields change (none →
    nothing_to_modify). ``confirm`` required only for a non-bridge (pre-existing) section
    (§5.1). ``dry_run`` previews with a per-field diff."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return sections_write_primitive.modify_rectangular_section(
            model, session.oapi_namespace(), name, request.material, request.depth,
            request.width, request.color, request.notes, request.dry_run, request.confirm,
        )


@app.post("/v1/sections/{name}/assign-to-frames", response_model=AssignmentResponse)
def assign_section_to_frames(name: str, request: AssignToFramesRequest) -> AssignmentResponse:
    """Assign ONE section to many frames (homogeneous batch — write). The section and every
    frame must exist (strict pre-validation → object_not_found). Empty list → empty_batch.
    ``confirm`` mandatory (touches pre-existing frames). ``dry_run`` previews with per-frame
    changes. A >10-frame result carries a ``hint``. failed_at is null in normal flow (only
    set on an unexpected mid-loop OAPI failure, with not_attempted)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return section_assignment_primitive.assign_section_to_frames(
            model, session.oapi_namespace(), name, request.frame_names,
            request.dry_run, request.confirm,
        )


@app.post("/v1/sections/assign-batch", response_model=AssignmentResponse)
def assign_sections_to_frames(request: AssignBatchRequest) -> AssignmentResponse:
    """Assign sections to frames per a heterogeneous frame→section mapping (write). Every
    referenced section and frame must exist (strict pre-validation). Empty → empty_batch.
    ``confirm`` mandatory; ``dry_run`` previews. Same applied/failed_at/not_attempted shape
    as the homogeneous endpoint. The OAPI has no native heterogeneous batch; the bridge
    composes a loop — the client does not see that detail."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return section_assignment_primitive.assign_sections_to_frames(
            model, session.oapi_namespace(),
            [a.model_dump() for a in request.assignments], request.dry_run, request.confirm,
        )


@app.get("/v1/materials", response_model=MaterialsResponse)
def get_materials() -> MaterialsResponse:
    """The material property catalogue defined in the model: name, raw SAP material
    type and basic mechanical facts (E, nu, thermal coeff, shear modulus, weight/mass
    per volume) when available. No interpretation — 'MGP10' is reported as its SAP type
    'NoDesign', not 'timber'. Values are in present units."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = materials_primitive.get_materials(model, session.oapi_namespace())
        return MaterialsResponse(units=present_units, count=len(rows), materials=rows)


@app.post("/v1/materials", response_model=CreateMaterialResponse)
def create_material(request: CreateMaterialRequest) -> CreateMaterialResponse:
    """Create a material (write — new object). ``name`` must carry the bridge namespace
    prefix (else prefix_required); ``material_type`` is an eMatType member name (unknown →
    unknown_material_type; SAP26 has no 'Wood'). An existing name → name_already_exists (SAP
    would otherwise overwrite silently). No confirm (new prefixed object). ``dry_run``
    previews. A new material has only defaults — set its properties next."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return materials_write_primitive.create_material(
            model, session.oapi_namespace(), request.name, request.material_type, request.dry_run
        )


@app.post(
    "/v1/materials/{name}/properties/isotropic",
    response_model=SetMaterialPropertiesIsotropicResponse,
)
def set_material_properties_isotropic(
    name: str, request: SetMaterialPropertiesIsotropicRequest
) -> SetMaterialPropertiesIsotropicResponse:
    """Set a material's isotropic properties (write). The material must exist (else
    object_not_found). ``confirm`` is required only for a NON-bridge (pre-existing) material
    (§5.1); a bridge-owned one needs none. ``dry_run`` previews. E/poisson/thermal are in
    the present units — the client must know what those are; the bridge converts nothing."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return materials_write_primitive.set_material_properties_isotropic(
            model, name, request.E, request.poisson_ratio, request.thermal_coef,
            request.dry_run, request.confirm,
        )


@app.get("/v1/load_patterns", response_model=LoadPatternsResponse)
def get_load_patterns() -> LoadPatternsResponse:
    """The load pattern catalogue defined in the model: name, raw eLoadPatternType and
    self-weight multiplier. Names are model-supplied labels relayed verbatim ('PESO
    PROPIO' stays as-is, not translated to 'Dead'); the bridge never assumes which
    patterns a model should have."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = load_patterns_primitive.get_load_patterns(model, session.oapi_namespace())
        return LoadPatternsResponse(units=present_units, count=len(rows), load_patterns=rows)


@app.post("/v1/load_patterns", response_model=CreateLoadPatternResponse)
def create_load_pattern(request: CreateLoadPatternRequest) -> CreateLoadPatternResponse:
    """Create a load pattern (write — Fase 1h.4). ``name`` must carry the bridge prefix;
    ``pattern_type`` is an eLoadPatternType name, case-insensitive (else unknown_load_pattern_type).
    ``confirm`` mandatory; ``dry_run`` previews. A blank model starts with only DEAD."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return load_patterns_primitive.create_load_pattern(
            model, session.oapi_namespace(), request.name, request.pattern_type,
            request.self_weight_multiplier, request.add_load_case, request.dry_run, request.confirm,
        )


@app.get("/v1/load_cases", response_model=LoadCasesResponse)
def get_load_cases() -> LoadCasesResponse:
    """The analysis load case catalogue: name + raw eLoadCaseType (LinearStatic, Modal,
    …). Facts only — the case's internal definition (patterns/factors it uses) is a
    later primitive."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = load_cases_primitive.get_load_cases(model, session.oapi_namespace())
        return LoadCasesResponse(units=present_units, count=len(rows), load_cases=rows)


@app.get("/v1/load_cases/{name}/details", response_model=LoadCaseDetailsResponse)
def get_load_case_details(name: str) -> LoadCaseDetailsResponse:
    """Composition of ONE load case (by exact name, as in /v1/load_cases). For a
    LinearStatic case, ``loads`` lists the applied patterns + scale factors (closing the
    asymmetry with /v1/combinations). For other case types, ``unsupported_case_type`` is
    true and ``loads`` is empty — the case and its type are reported, internals deferred."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        case = load_case_details_primitive.get_load_case_details(
            model, session.oapi_namespace(), name
        )
        return LoadCaseDetailsResponse(units=present_units, case=case)


@app.get("/v1/combinations", response_model=CombinationsResponse)
def get_combinations() -> CombinationsResponse:
    """The load combination catalogue: each combo's name, type (mapped from SAP's raw
    code) and consolidated component items (referenced case/combo + scale factor). The
    bridge recomposes SAP's parallel arrays so the client doesn't; it interprets
    nothing — 'ENVOLVENTE' is reported with combo_type 'Envelope', no domain labels."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = combinations_primitive.get_combinations(model)
        return CombinationsResponse(units=present_units, count=len(rows), combinations=rows)


# --- Mutating operations -----------------------------------------------------
# The bridge is read-only except here: running analysis changes the model's COMPUTATION
# state (it produces results and may lock the model). It is POST to signal that intent.
# It does NOT modify the model definition (that is Fase 1g, gated behind a design doc).


@app.post("/v1/analysis/run", response_model=AnalysisRunResponse)
def run_analysis(request: AnalysisRunRequest | None = None) -> AnalysisRunResponse:
    """Run the analysis (BLOCKING — synchronous; large models can take a while). With no
    body, runs all pending cases. With ``cases_to_run``, runs only those by name (validated
    against existing cases first; the model's run-case flags are restored afterwards). A
    non-zero RunAnalysis return surfaces as oapi_call_failed — the bridge relays the code,
    it does not interpret a model-side failure. Re-running is idempotent (SAP skips cases
    with current results), so no confirmation is required."""
    req = request or AnalysisRunRequest()
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return analysis_primitive.run_analysis(model, req.cases_to_run)


@app.get("/v1/analysis/status", response_model=AnalysisStatusResponse)
def get_analysis_status() -> AnalysisStatusResponse:
    """Current analysis status per load case (has_run + raw/named status) plus
    model_is_locked. Facts only — 'locked' means results would be invalidated by editing
    the model; the bridge does not judge it."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return analysis_primitive.get_analysis_status(model)


# --- Analysis results (read-only post-analysis) ------------------------------
# These read results the analysis produced. They depend on computation state: a case
# that has not been run returns case_not_run; a non-LinearStatic case returns
# unsupported_case_type. Values are in present units (the bridge never converts).


@app.get("/v1/joints/{name}/displacements/{case_name}", response_model=JointDisplacementsResponse)
def get_joint_displacements(name: str, case_name: str) -> JointDisplacementsResponse:
    """6-DOF displacement of one joint in one LinearStatic case (global, present units).
    Restrained DOFs read ~0, reported as SAP gives them. case_not_run if the case has no
    results; unsupported_case_type if it is not LinearStatic."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        disp = joint_results_primitive.get_joint_displacements(
            model, session.oapi_namespace(), name, case_name
        )
        return JointDisplacementsResponse(units=present_units, displacements=disp)


@app.get("/v1/joints/{name}/reactions/{case_name}", response_model=JointReactionsResponse)
def get_joint_reactions(name: str, case_name: str) -> JointReactionsResponse:
    """6-DOF reaction (force + moment) of one joint in one LinearStatic case (global,
    present units). Unrestrained DOFs read ~0; a free joint reads the zero vector — a
    fact, not an error. case_not_run / unsupported_case_type as above."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        react = joint_results_primitive.get_joint_reactions(
            model, session.oapi_namespace(), name, case_name
        )
        return JointReactionsResponse(units=present_units, reactions=react)


@app.get("/v1/frames/{name}/forces/{case_name}", response_model=FrameForcesResponse)
def get_frame_forces(
    name: str,
    case_name: str,
    station: float | None = Query(None, ge=0.0, le=1.0, description="Relative station 0..1; omit for all"),
) -> FrameForcesResponse:
    """Internal forces (P, V2, V3, T, M2, M3) at the stations along one frame in one
    LinearStatic case (present units). ``station`` (0..1) returns just that station; omit
    for all SAP computed. case_not_run / unsupported_case_type as above."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        present_units = units_primitive.get_present_units(model)
        rows = frame_results_primitive.get_frame_forces(
            model, session.oapi_namespace(), name, case_name, station
        )
        return FrameForcesResponse(
            units=present_units, frame=name, case_name=case_name, count=len(rows), stations=rows
        )


# --- Write-side: savepoints (undo infrastructure, Fase 1g.1) -----------------
# The first write primitives. They write the FILESYSTEM (separate .sdb files), not the
# model in memory — the rollback net the rest of the write-side builds on. POST mutates;
# GET (list) is a pure filesystem scan. See docs/write_side_design.md.


@app.post("/v1/savepoints", response_model=SavepointCreateResponse)
def create_savepoint(request: SavepointCreateRequest) -> SavepointCreateResponse:
    """Save the current model state to a savepoint .sdb file (<model>__sp_<name>.sdb).
    Refuses if a savepoint of that name already exists (no silent overwrite). ``dry_run``
    previews the target path + writability without writing. Internally: Save then reopen
    the original, so the session keeps pointing at the user's model."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return savepoints_primitive.create_savepoint(
            model, session.workspace, request.name, request.dry_run
        )


@app.post("/v1/savepoints/{name}/restore", response_model=SavepointRestoreResponse)
def restore_savepoint(name: str, request: SavepointRestoreRequest | None = None) -> SavepointRestoreResponse:
    """Restore a savepoint, replacing the loaded model with it. Destructive →
    ``confirm=true`` is mandatory (else confirm_required) unless ``dry_run``. Missing
    savepoint → savepoint_not_found. The SAP handle stays valid after the reopen."""
    req = request or SavepointRestoreRequest()
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return savepoints_primitive.restore_savepoint(
            model, session.workspace, name, req.confirm, req.dry_run
        )


@app.get("/v1/savepoints", response_model=SavepointListResponse)
def list_savepoints() -> SavepointListResponse:
    """List the savepoints for the current model (filesystem scan; empty list if none)."""
    session = get_session()
    with session.lock():
        model = session.sap_model()
        return savepoints_primitive.list_savepoints(model)
