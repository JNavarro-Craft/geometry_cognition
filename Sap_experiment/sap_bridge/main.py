"""FastAPI app for the SAP bridge — the single HTTP integration point with SAP2000.

Runs on localhost:8766 (geometry_cognition's Rhino bridge uses 8765; SAP gets 8766).
Endpoints are versioned under /v1 and every failure returns a structured
ErrorResponse so all consumers — MCP, Rhino plugins, scripts — branch on a stable
code. This module wires routes to the read-only primitives; it holds no domain logic.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import error_codes
from .contracts import (
    CombinationsResponse,
    DistributedLoadsResponse,
    ErrorResponse,
    FramesResponse,
    HealthResponse,
    JointsResponse,
    LoadCaseDetailsResponse,
    LoadCasesResponse,
    LoadPatternsResponse,
    MaterialsResponse,
    PointLoadsResponse,
    SectionPropertiesResponse,
    SectionsResponse,
    UnitsResponse,
)
from .path_resolver import resolve_oapi_dll
from .primitives import combinations as combinations_primitive
from .primitives import frame_loads as frame_loads_primitive
from .primitives import frames as frames_primitive
from .primitives import joint_loads as joint_loads_primitive
from .primitives import joints as joints_primitive
from .primitives import load_case_details as load_case_details_primitive
from .primitives import load_cases as load_cases_primitive
from .primitives import load_patterns as load_patterns_primitive
from .primitives import materials as materials_primitive
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
