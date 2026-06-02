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
    MaterialsResponse,
    ModelSettingsResponse,
    PointLoadsResponse,
    SectionPropertiesResponse,
    SectionsResponse,
    UnitsResponse,
)
from .path_resolver import resolve_oapi_dll
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
from .primitives import model_settings as model_settings_primitive
from .primitives import section_properties as section_properties_primitive
from .primitives import sections as sections_primitive
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
