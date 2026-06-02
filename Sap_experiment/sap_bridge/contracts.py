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
