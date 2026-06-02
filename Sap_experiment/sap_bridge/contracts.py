"""HTTP contract for the SAP bridge — pydantic models shared by every endpoint.

This is a PUBLIC contract. Today the only consumer is the MCP (sap_developer_server),
but per the project brief the bridge is the single integration point with SAP2000:
Rhino plugins and standalone scripts (Objetivo 2) will depend on these exact shapes.
So the conventions here are deliberate and meant to be stable:

  * Every successful list response carries ``units`` (the active SAP unit system as a
    bare fact) and a ``count``. Units are EXPOSED, never silently converted — the
    client converts knowing what it has on each side.
  * Every failure is an ``ErrorResponse`` ({error, code, message}) with the same
    shape regardless of endpoint, mirroring geometry_cognition's bridge.
  * Field names report FACTS (coordinates, connectivity, property names), never
    judgements. No ``is_*`` / ``verify_*`` / domain words anywhere.

Versioned under ``/v1`` from day one.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Structured error body. Returned with a 4xx/5xx status for every failure so
    callers branch on ``code`` (stable, from error_codes) rather than parsing prose."""

    error: bool = True
    code: str = Field(..., description="Stable machine-readable code from error_codes")
    message: str = Field(..., description="Human-readable detail; may include OAPI status")


class HealthResponse(BaseModel):
    status: str = Field(..., description="'ok' if the bridge process is up")
    sap_attached: bool = Field(..., description="True if a live SAP2000 session is attached")
    oapi_dll: str | None = Field(None, description="Resolved SAP2000v1.dll path, if found")


class UnitsResponse(BaseModel):
    """The active SAP2000 unit system, exposed as a fact (see RhinoSAP/UnitConversion
    note in the brief: convert at the client, never silently in the bridge)."""

    present_units: str = Field(..., description="SAP eUnits name for the present units, e.g. 'kgf_m_C'")
    present_units_code: int = Field(..., description="Raw eUnits integer value")


class Joint(BaseModel):
    """One point object: its name, Cartesian coordinates and DOF restraints.

    ``restraints`` is the raw 6-tuple SAP returns (U1,U2,U3,R1,R2,R3) as booleans —
    True = restrained. The bridge does not name it 'pinned'/'fixed'; that mapping is
    domain and lives in the client.
    """

    name: str
    x: float
    y: float
    z: float
    coord_system: str = Field("Global", description="Coordinate system the x/y/z are in")
    restraints: list[bool] = Field(
        ..., description="6 DOF restraint flags [U1,U2,U3,R1,R2,R3]; True = restrained"
    )


class JointsResponse(BaseModel):
    units: UnitsResponse
    count: int
    joints: list[Joint]


class Frame(BaseModel):
    """One frame (line) object: its name, the two end point names (connectivity) and
    the assigned section property name. ``auto_select`` is SAP's flag for an
    auto-select section list; reported as a fact, not interpreted."""

    name: str
    point_i: str
    point_j: str
    section: str = Field(..., description="Assigned frame section property name (raw)")
    auto_select: str = Field("", description="SAP auto-select list name, '' if none")


class FramesResponse(BaseModel):
    units: UnitsResponse
    count: int
    frames: list[Frame]


class Section(BaseModel):
    """One frame section property defined in the model: its name and SAP property
    type. ``prop_type`` is the raw eFramePropType name (e.g. 'Rectangular'); the
    bridge does not resolve geometric dimensions here (that is a later primitive)."""

    name: str
    prop_type: str = Field(..., description="Raw eFramePropType name for the section")


class SectionsResponse(BaseModel):
    units: UnitsResponse
    count: int
    sections: list[Section]


class Material(BaseModel):
    """One material property defined in the model: its name, raw SAP material type and
    basic mechanical properties as SAP reports them.

    ``mat_type`` is the raw eMatType member name (e.g. 'Steel', 'Concrete',
    'NoDesign') — a fact, never an interpretation. A name like 'MGP10' may be timber to
    a human, but SAP reports it as 'NoDesign'; the bridge relays that and does not
    rename it. Mechanical fields come from GetMPIsotropic / GetWeightAndMass and are in
    the model's present units (echoed in the response). They are Optional because not
    every material type is isotropic; absent values are reported as null, never faked.
    """

    name: str
    mat_type: str = Field(..., description="Raw eMatType member name (Steel/Concrete/NoDesign/…)")
    e: float | None = Field(None, description="Modulus of elasticity E (isotropic), present units")
    nu: float | None = Field(None, description="Poisson's ratio U (isotropic), dimensionless")
    thermal_coeff: float | None = Field(None, description="Thermal expansion coefficient A (isotropic)")
    shear_modulus: float | None = Field(None, description="Shear modulus G (isotropic), present units")
    weight_per_volume: float | None = Field(None, description="Specific weight W, present units")
    mass_per_volume: float | None = Field(None, description="Specific mass M, present units")


class MaterialsResponse(BaseModel):
    units: UnitsResponse
    count: int
    materials: list[Material]


class SectionProperties(BaseModel):
    """Geometric dimensions and universal section properties of ONE frame section.

    ``dimensions`` holds the shape-specific geometry (depth/width for Rectangular,
    diameter for Circle, …) keyed by SAP's own parameter names, in present units. It is
    a dict because the key set varies by ``prop_type``; the bridge does not normalize
    across shapes (that would be interpretation). ``properties`` holds the universal
    section properties (area, inertias, …) that GetSectProps returns for any shape.
    ``material`` is the material property name the section references (a fact; join with
    /v1/materials). All values are in the model's present units, echoed in the response.
    """

    name: str
    prop_type: str = Field(..., description="Raw eFramePropType member name for this section")
    material: str = Field(..., description="Referenced material property name (raw)")
    dimensions: dict[str, float] = Field(
        ..., description="Shape-specific geometry keyed by SAP parameter name, present units"
    )
    properties: dict[str, float] = Field(
        ..., description="Universal section properties (area, inertias, …), present units"
    )


class SectionPropertiesResponse(BaseModel):
    units: UnitsResponse
    section: SectionProperties


class LoadPattern(BaseModel):
    """One load pattern defined in the model: its name, raw SAP type and self-weight
    multiplier.

    ``load_type`` is the raw eLoadPatternType member name (e.g. 'Dead', 'Live', 'Wind',
    'Snow') — a fact. A name like 'PESO PROPIO' is a model-supplied label relayed
    verbatim; the bridge does not translate it to 'Dead' or know it is Spanish.
    ``self_weight_multiplier`` is the factor SAP applies to the pattern's self weight
    (typically 1.0 for a self-weight pattern, 0.0 otherwise).
    """

    name: str
    load_type: str = Field(..., description="Raw eLoadPatternType member name (Dead/Live/Wind/…)")
    self_weight_multiplier: float = Field(..., description="Self-weight multiplier for this pattern")


class LoadPatternsResponse(BaseModel):
    units: UnitsResponse
    count: int
    load_patterns: list[LoadPattern]


class LoadCase(BaseModel):
    """One analysis load case defined in the model: its name and raw SAP case type.

    ``case_type`` is the raw eLoadCaseType member name (e.g. 'LinearStatic',
    'Modal'). The bridge reports the type as a fact and does not resolve the case's
    internal definition (which patterns/factors it uses) — that is a later primitive.
    """

    name: str
    case_type: str = Field(..., description="Raw eLoadCaseType member name (LinearStatic/Modal/…)")


class LoadCasesResponse(BaseModel):
    units: UnitsResponse
    count: int
    load_cases: list[LoadCase]


class ComboItem(BaseModel):
    """One component of a load combination: a referenced case/combo and its scale factor.

    SAP returns combination contents as parallel arrays (NumberItems + CName[] +
    CNameType[] + SF[]); the bridge consolidates them into a list of these objects so
    the client never recomposes indices. ``case_type`` distinguishes whether
    ``case_name`` references a load case ('LoadCase') or another combination
    ('LoadCombo') — the raw eCNameType member name.
    """

    case_name: str = Field(..., description="Referenced case or combo name (raw)")
    case_type: str = Field(..., description="Raw eCNameType: 'LoadCase' or 'LoadCombo'")
    scale_factor: float = Field(..., description="Scale factor applied to this component")


class Combination(BaseModel):
    """One load combination defined in the model: its name, type and component items.

    ``combo_type_code`` is the raw integer SAP returns (this assembly exposes no
    eComboType enum). ``combo_type`` is the corresponding SAP type name from the OAPI's
    documented mapping (0=Linear Additive, 1=Envelope, 2=Absolute Add, 3=SRSS,
    4=Range Add); 'Unknown' if SAP returns a code outside that set — reported, never
    guessed. ``items`` is the consolidated component list (see ComboItem).
    """

    name: str
    combo_type: str = Field(..., description="SAP combo type name from the documented code mapping")
    combo_type_code: int = Field(..., description="Raw integer combo type from GetTypeOAPI")
    items: list[ComboItem]


class CombinationsResponse(BaseModel):
    units: UnitsResponse
    count: int
    combinations: list[Combination]


class DistributedLoad(BaseModel):
    """One distributed load on a frame, in one load pattern.

    All fields are facts SAP returns. ``load_type`` is the raw type ('Force' or
    'Displacement'). ``direction_code`` is the raw integer SAP uses for the load
    direction (this assembly exposes no direction enum, same as combo_type); ``direction``
    is the documented name for that code (1-3=Local, 4-6=Global X/Y/Z, 7-9=Projected,
    10=Gravity, 11=Projected Gravity), 'Unknown' if the code is outside that set —
    reported, never guessed. ``coord_system`` is the raw CSys name ('GLOBAL', 'Local', a
    custom name). ``rel_dist_start``/``end`` are the 0..1 relative positions; ``value_*``
    are the load magnitudes in the model's present units. No interpretation: 'Gravity'
    stays 'Gravity', not 'down'.
    """

    load_pattern: str = Field(..., description="Load pattern name this load belongs to (raw)")
    load_type: str = Field(..., description="Raw load type: 'Force' or 'Displacement'")
    direction: str = Field(..., description="Documented direction name for direction_code")
    direction_code: int = Field(..., description="Raw integer load direction from the OAPI")
    coord_system: str = Field(..., description="Raw coordinate system name (GLOBAL/Local/custom)")
    rel_dist_start: float = Field(..., description="Relative start position along the frame, 0..1")
    rel_dist_end: float = Field(..., description="Relative end position along the frame, 0..1")
    value_start: float = Field(..., description="Load value at start, present units")
    value_end: float = Field(..., description="Load value at end, present units")


class DistributedLoadsResponse(BaseModel):
    units: UnitsResponse
    frame: str
    count: int
    loads: list[DistributedLoad]


class PointLoad(BaseModel):
    """One point load (force + moment) on a joint, in one load pattern.

    ``f1/f2/f3`` and ``m1/m2/m3`` are the force and moment components in ``coord_system``,
    in the model's present units. Raw facts; the bridge does not resolve the coordinate
    system or name the direction.
    """

    load_pattern: str = Field(..., description="Load pattern name this load belongs to (raw)")
    coord_system: str = Field(..., description="Raw coordinate system name the components are in")
    f1: float = Field(..., description="Force component 1, present units")
    f2: float = Field(..., description="Force component 2, present units")
    f3: float = Field(..., description="Force component 3, present units")
    m1: float = Field(..., description="Moment component 1, present units")
    m2: float = Field(..., description="Moment component 2, present units")
    m3: float = Field(..., description="Moment component 3, present units")


class PointLoadsResponse(BaseModel):
    units: UnitsResponse
    joint: str
    count: int
    loads: list[PointLoad]


class LoadCaseLoadItem(BaseModel):
    """One component of a LinearStatic load case: a load pattern and its scale factor.

    ``load_type`` is the raw type SAP reports for the entry ('Load' for a load pattern).
    Mirrors ComboItem in shape so case composition reads like combo composition.
    """

    load_type: str = Field(..., description="Raw load entry type (e.g. 'Load')")
    load_pattern: str = Field(..., description="Referenced load pattern name (raw)")
    scale_factor: float = Field(..., description="Scale factor applied to this load")


class LoadCaseDetails(BaseModel):
    """The composition of one load case: its type and the loads it applies.

    For ``case_type == 'LinearStatic'``, ``loads`` lists the applied load patterns with
    scale factors. For any other case type (Modal, ResponseSpectrum, …) the bridge does
    not resolve composition this phase: ``loads`` is empty and ``unsupported_case_type``
    is True — the case exists and its type is reported, but its internals are deferred
    (information, not an error).
    """

    case_name: str
    case_type: str = Field(..., description="Raw eLoadCaseType member name")
    unsupported_case_type: bool = Field(
        False, description="True if composition is not resolved for this case type this phase"
    )
    loads: list[LoadCaseLoadItem]


class LoadCaseDetailsResponse(BaseModel):
    units: UnitsResponse
    case: LoadCaseDetails
