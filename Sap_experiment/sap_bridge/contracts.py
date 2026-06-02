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


class AnalysisRunRequest(BaseModel):
    """Request body for POST /v1/analysis/run.

    ``cases_to_run`` None means "run whatever SAP has pending" (the default
    RunAnalysis behaviour). A list runs only those cases by name; the bridge validates
    every name exists before touching SAP and restores the model's run-case flags
    afterwards so the request leaves no side effect on which cases are flagged.
    """

    cases_to_run: list[str] | None = Field(
        None, description="Case names to run; None runs all pending cases"
    )


class CaseStatus(BaseModel):
    """Analysis status of one load case, as a fact.

    ``status_code`` is the raw integer SAP returns from GetCaseStatus; ``status`` is its
    documented name (1=Not Run, 2=Could Not Start, 3=Not Finished, 4=Finished),
    'Unknown' for an unmapped code. ``has_run`` is True only when status is Finished
    (results exist). A case that could not start / did not finish is reported as the
    fact it is — the bridge never says the model is wrong.
    """

    case_name: str
    status: str = Field(..., description="Documented status name for status_code")
    status_code: int = Field(..., description="Raw integer case status from GetCaseStatus")
    has_run: bool = Field(..., description="True if results exist (status Finished)")


class AnalysisRunResponse(BaseModel):
    """Result of a run. ``cases_run`` lists the cases that reached Finished during/after
    this run; ``ran_count`` its length. ``runtime_seconds`` is the wall-clock time the
    (blocking) RunAnalysis call took. ``model_is_locked`` reflects the post-run lock
    state. ``status`` is the per-case status snapshot after the run.
    """

    ran_count: int
    cases_run: list[str]
    runtime_seconds: float
    model_is_locked: bool
    status: list[CaseStatus]


class AnalysisStatusResponse(BaseModel):
    """Current analysis status: per-case status plus whether the model is locked. A
    locked model holds results that would be invalidated by modifying the model — a
    fact for the client, not a judgement."""

    model_is_locked: bool
    count: int
    status: list[CaseStatus]


class JointDisplacements(BaseModel):
    """The 6-DOF displacement vector of one joint in one load case, as a fact.

    ``u1/u2/u3`` are translations and ``r1/r2/r3`` rotations in the global system, in the
    model's present units. For a restrained DOF the value comes back ~0 (reported as SAP
    gives it, never nullified). LinearStatic only this phase, so ``step_number`` is 0.
    """

    joint: str
    case_name: str
    coord_system: str = Field("Global", description="Coordinate system of the components")
    step_number: float = Field(0.0, description="Result step (0 for LinearStatic)")
    u1: float = Field(..., description="Translation U1, present units")
    u2: float = Field(..., description="Translation U2, present units")
    u3: float = Field(..., description="Translation U3, present units")
    r1: float = Field(..., description="Rotation R1, present units")
    r2: float = Field(..., description="Rotation R2, present units")
    r3: float = Field(..., description="Rotation R3, present units")


class JointDisplacementsResponse(BaseModel):
    units: UnitsResponse
    displacements: JointDisplacements


class JointReactions(BaseModel):
    """The 6-DOF reaction (force + moment) of one joint in one load case, as a fact.

    ``f1/f2/f3`` are forces and ``m1/m2/m3`` moments in the global system, present units.
    A DOF that is not restrained reads ~0 (reported as-is); a joint with no restraint at
    all reads the zero vector SAP returns — correct information, not an error.
    """

    joint: str
    case_name: str
    coord_system: str = Field("Global", description="Coordinate system of the components")
    step_number: float = Field(0.0, description="Result step (0 for LinearStatic)")
    f1: float = Field(..., description="Reaction force F1, present units")
    f2: float = Field(..., description="Reaction force F2, present units")
    f3: float = Field(..., description="Reaction force F3, present units")
    m1: float = Field(..., description="Reaction moment M1, present units")
    m2: float = Field(..., description="Reaction moment M2, present units")
    m3: float = Field(..., description="Reaction moment M3, present units")


class JointReactionsResponse(BaseModel):
    units: UnitsResponse
    reactions: JointReactions


class FrameForceStation(BaseModel):
    """Internal forces at one station along a frame, in one load case.

    ``relative_distance`` is 0..1 along the frame; ``absolute_distance`` is in present
    length units. ``p`` is axial, ``v2``/``v3`` shears, ``t`` torsion, ``m2``/``m3``
    moments — all in present units, all facts. A large value is not a judgement of
    failure (anti-pattern #4).
    """

    relative_distance: float = Field(..., description="Station position 0..1 along the frame")
    absolute_distance: float = Field(..., description="Station distance from i-end, present units")
    p: float = Field(..., description="Axial force P, present units")
    v2: float = Field(..., description="Shear V2, present units")
    v3: float = Field(..., description="Shear V3, present units")
    t: float = Field(..., description="Torsion T, present units")
    m2: float = Field(..., description="Moment M2, present units")
    m3: float = Field(..., description="Moment M3, present units")


class FrameForcesResponse(BaseModel):
    units: UnitsResponse
    frame: str
    case_name: str
    count: int
    stations: list[FrameForceStation]


class ModelSettings(BaseModel):
    """Model configuration facts: structural envelope (active DOFs + lock state) and
    units (present + database).

    ``active_dof`` is the raw 6-tuple SAP returns from GetActiveDOF, in the standard order
    [U1, U2, U3, R1, R2, R3] — the same index convention as joint restraints/reactions/
    displacements. The bridge does NOT name a pattern: [true,false,true,false,true,false]
    is reported as-is, never labelled 'Plane Frame XZ' (the client recognises that).
    ``present_units`` is the active 'view'; ``database_units`` is the system the model
    stores data in internally. They may differ; both are reported as facts.
    """

    active_dof: list[bool] = Field(
        ..., description="6 active-DOF flags [U1,U2,U3,R1,R2,R3]; True = active"
    )
    model_is_locked: bool = Field(
        ..., description="True if analysis results are current (editing would invalidate them)"
    )
    present_units: UnitsResponse
    database_units: UnitsResponse


class ModelSettingsResponse(BaseModel):
    settings: ModelSettings


# --- Write-side: savepoints (Fase 1g.1) --------------------------------------
# These are the first write primitives. They write to the FILESYSTEM (separate .sdb
# files), not to the SAP model in memory — the undo infrastructure the rest of the
# write-side builds on. See docs/write_side_design.md.


class SavepointCreateRequest(BaseModel):
    """Body for POST /v1/savepoints. ``dry_run`` (write_side_design.md §2) previews the
    target path + writability without creating the file."""

    name: str = Field(..., description="Savepoint name; the file is <model>__sp_<name>.sdb")
    dry_run: bool = Field(False, description="If true, preview only — no file written")


class SavepointRestoreRequest(BaseModel):
    """Body for POST /v1/savepoints/{name}/restore. Restore replaces the loaded model, so
    ``confirm`` is mandatory (write_side_design.md §5); ``dry_run`` previews instead."""

    confirm: bool = Field(False, description="Must be true to actually restore (destructive)")
    dry_run: bool = Field(False, description="If true, preview only — model not replaced")


class SavepointInfo(BaseModel):
    """One savepoint on disk: name, absolute path, creation timestamp (ISO-8601) and
    file size in bytes. Pure filesystem facts."""

    name: str
    path: str = Field(..., description="Absolute path of the savepoint .sdb file")
    created_at: str = Field(..., description="File creation time, ISO-8601")
    size_bytes: int = Field(..., description="File size in bytes")


class SavepointListResponse(BaseModel):
    """All savepoints for the current model. Empty list (not an error) if none. Works
    from a pure filesystem scan — no OAPI/SAP attach required."""

    model_name: str
    count: int
    savepoints: list[SavepointInfo]


class SavepointCreateResponse(BaseModel):
    """Result of create_savepoint. In dry-run, ``dry_run`` is true, ``would_apply`` holds
    the target the write would produce and ``applied`` is null; in a real run it is the
    reverse (write_side_design.md §2). ``would_apply``/``applied`` are SavepointInfo
    (``size_bytes`` is an estimate in dry-run, the model's current file size)."""

    dry_run: bool
    validation_passed: bool = Field(True, description="Dry-run pre-validation result")
    would_apply: SavepointInfo | None = None
    applied: SavepointInfo | None = None


class SavepointRestoreResponse(BaseModel):
    """Result of restore_savepoint. ``would_replace_with`` (dry-run) / ``restored_from``
    (real) is the savepoint that is/would be loaded. ``model_file`` is the model path the
    session points at after the operation."""

    dry_run: bool
    would_replace_with: SavepointInfo | None = None
    restored_from: SavepointInfo | None = None
    model_file: str | None = Field(None, description="Model path the session points at after restore")


# --- Write-side: set_active_dof (Fase 1g.2) ----------------------------------
# The first primitive that mutates the SAP model in memory. A global model setting, so
# confirm is mandatory (write_side_design.md §5.3); dry_run previews the change.


class SetActiveDOFRequest(BaseModel):
    """Body for POST /v1/model/settings/active_dof. ``active_dof`` must be exactly 6
    booleans [U1,U2,U3,R1,R2,R3]. ``confirm`` is mandatory (global setting); ``dry_run``
    previews. The bridge validates shape only — it does NOT judge whether a DOF pattern is
    structurally sensible (anti-pattern #4; SAP itself accepts even all-false)."""

    active_dof: list[bool] = Field(..., description="Exactly 6 DOF flags [U1,U2,U3,R1,R2,R3]")
    dry_run: bool = Field(False, description="If true, preview the change without applying")
    confirm: bool = Field(False, description="Must be true to apply (global setting)")


class ActiveDOFChange(BaseModel):
    """The active-DOF change as facts: the vectors and a human-readable per-DOF diff."""

    current_active_dof: list[bool] | None = Field(
        None, description="Current vector (dry-run preview)"
    )
    previous_active_dof: list[bool] | None = Field(
        None, description="Vector before applying (real run)"
    )
    new_active_dof: list[bool] | None = Field(None, description="Target vector (dry-run preview)")
    changes: list[str] = Field(
        ..., description="Per-DOF diffs, e.g. ['U2: false → true', 'R1: false → true']"
    )


class SetActiveDOFResponse(BaseModel):
    """Result of set_active_dof. Dry-run: ``dry_run`` true, ``would_apply`` holds the
    preview (current/new/changes), ``validation_passed`` true, ``applied`` null. Real run:
    the reverse — ``applied`` holds previous/current/changes. ``model_is_locked`` is the
    post-operation lock state (relayed, never auto-changed by the bridge)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: ActiveDOFChange | None = None
    applied: ActiveDOFChange | None = None
    model_is_locked: bool | None = Field(None, description="Lock state after the operation")


# --- Write-side: set_present_units (Fase 1g.3) -------------------------------
# Second global-setting write — same template as set_active_dof. Changing present units is
# a DISPLAY preference (it reformats how values are reported), not a data conversion; the
# read-side then reports in the new system. database_units is NOT touched (that would
# convert stored data — out of scope).


class SetPresentUnitsRequest(BaseModel):
    """Body for POST /v1/model/settings/present_units. ``units`` is the eUnits member NAME
    (e.g. 'N_m_C', 'kgf_m_C') — the bridge resolves name → enum. ``confirm`` mandatory
    (global setting); ``dry_run`` previews."""

    units: str = Field(..., description="Unit-system name (eUnits member, e.g. 'N_m_C')")
    dry_run: bool = Field(False, description="If true, preview the change without applying")
    confirm: bool = Field(False, description="Must be true to apply (global setting)")


class UnitsChange(BaseModel):
    """A present-units change as facts: the units before/after (name + code) and a summary.

    Each units value reuses the existing UnitsResponse shape (name in ``present_units``,
    int in ``present_units_code``) so the units contract stays consistent across endpoints.
    """

    current_units: UnitsResponse | None = Field(None, description="Current units (dry-run)")
    new_units: UnitsResponse | None = Field(None, description="Target units (dry-run)")
    previous_units: UnitsResponse | None = Field(None, description="Units before applying (real)")
    change_summary: str = Field(..., description="e.g. 'kgf_m_C → N_m_C'")


class SetPresentUnitsResponse(BaseModel):
    """Result of set_present_units. Dry-run: ``would_apply`` (current/new/summary),
    ``applied`` null. Real run: ``applied`` (previous/current/summary). ``model_is_locked``
    echoed as a fact (changing present units does not change the lock state)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: UnitsChange | None = None
    applied: UnitsChange | None = None
    model_is_locked: bool | None = Field(None, description="Lock state after the operation")


# --- Write-side: create_material + isotropic properties (Fase 1g.4) ----------
# First write over individual OBJECTS. create_material enforces the namespace prefix
# (write_side_design.md §1) — the bridge only creates in its own namespace. Creating an
# object and setting its properties are SEPARATE atomic primitives (no composite).


class CreateMaterialRequest(BaseModel):
    """Body for POST /v1/materials. ``name`` must carry the bridge prefix (else
    prefix_required). ``material_type`` is an eMatType member NAME (e.g. 'Steel',
    'Concrete', 'NoDesign' — note SAP26 has no 'Wood'). No confirm needed (creating a new
    prefixed object). ``dry_run`` previews."""

    name: str = Field(..., description="New material name; must start with the bridge prefix")
    material_type: str = Field(..., description="eMatType member name (e.g. 'NoDesign')")
    dry_run: bool = Field(False, description="If true, preview without creating")


class MaterialCreation(BaseModel):
    """The created (or to-be-created) material as facts: name, type name and raw type code.

    A freshly created material has only default/empty mechanical properties — call
    set_material_properties_isotropic next to make it usable (atomic separation).
    """

    name: str
    material_type: str = Field(..., description="eMatType member name")
    type_code: int = Field(..., description="Raw eMatType integer value")


class CreateMaterialResponse(BaseModel):
    """Result of create_material. Dry-run: ``would_apply``, ``applied`` null; real run the
    reverse. No confirm (create of a prefixed object is non-destructive)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: MaterialCreation | None = None
    applied: MaterialCreation | None = None


class IsotropicProperties(BaseModel):
    """Isotropic mechanical properties, in the model's present units. ``shear_modulus`` is
    derived by SAP from E and nu (G = E / (2(1+nu))); reported as a fact, not an input."""

    e: float = Field(..., description="Modulus of elasticity E, present units")
    poisson_ratio: float = Field(..., description="Poisson's ratio U (dimensionless)")
    thermal_coef: float = Field(..., description="Thermal expansion coefficient A")
    shear_modulus: float | None = Field(None, description="Shear modulus G (derived by SAP)")


class SetMaterialPropertiesIsotropicRequest(BaseModel):
    """Body for POST /v1/materials/{name}/properties/isotropic. ``confirm`` is required only
    when ``name`` has no bridge prefix (modifying a pre-existing material, §5.1); for a
    bridge-owned material it is not. ``dry_run`` previews. Values are in the present units —
    the client is responsible for knowing what those are (the bridge converts nothing)."""

    E: float = Field(..., description="Modulus of elasticity, present units")
    poisson_ratio: float = Field(..., description="Poisson's ratio")
    thermal_coef: float = Field(..., description="Thermal expansion coefficient")
    dry_run: bool = Field(False, description="If true, preview without applying")
    confirm: bool = Field(False, description="Required to modify a non-bridge (pre-existing) material")


class IsotropicPropertiesChange(BaseModel):
    """The properties change as facts: before/after sets and a readable per-field diff."""

    current_properties: IsotropicProperties | None = Field(None, description="Current (dry-run)")
    new_properties: IsotropicProperties | None = Field(None, description="Proposed (dry-run)")
    previous_properties: IsotropicProperties | None = Field(None, description="Before (real run)")
    changes: list[str] = Field(..., description="Per-field diffs, e.g. ['E: 8.5e9 → 9.0e9']")


class SetMaterialPropertiesIsotropicResponse(BaseModel):
    """Result of set_material_properties_isotropic. Dry-run: ``would_apply``
    (current/new/changes); real run: ``applied`` (previous/current/changes)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: IsotropicPropertiesChange | None = None
    applied: IsotropicPropertiesChange | None = None


# --- Write-side: rectangular sections (Fase 1g.5) ----------------------------
# Second object type under the create+modify template. Material is always required.
# SetRectangle overwrites a same-named section silently (like SetMaterial) — the
# name_already_exists guard is essential.


class CreateRectangularSectionRequest(BaseModel):
    """Body for POST /v1/sections. ``name`` must carry the bridge prefix; ``material`` must
    be an existing material; ``depth`` (T3) and ``width`` (T2) must be > 0. No confirm
    (new prefixed object). ``dry_run`` previews."""

    name: str = Field(..., description="New section name; must start with the bridge prefix")
    material: str = Field(..., description="Existing material name to assign")
    depth: float = Field(..., description="Section depth T3 (>0), present length units")
    width: float = Field(..., description="Section width T2 (>0), present length units")
    color: int | None = Field(None, description="SAP color index; default if omitted")
    notes: str = Field("", description="Free-text notes")
    dry_run: bool = Field(False, description="If true, preview without creating")


class RectangularSection(BaseModel):
    """A rectangular section's defining facts: name, material, dimensions, color, notes.
    ``prop_type`` is always 'Rectangular' here; the section_type is echoed for clarity."""

    name: str
    material: str
    depth: float = Field(..., description="T3, present length units")
    width: float = Field(..., description="T2, present length units")
    color: int
    notes: str
    section_type: str = Field("Rectangular", description="Raw eFramePropType member name")


class CreateRectangularSectionResponse(BaseModel):
    """Result of create_rectangular_section. Dry-run: ``would_apply``; real run:
    ``applied`` (read back from SAP so any normalization is reported)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: RectangularSection | None = None
    applied: RectangularSection | None = None


class ModifyRectangularSectionRequest(BaseModel):
    """Body for PATCH /v1/sections/{name}. Every field is optional — only the provided ones
    change (all None → nothing_to_modify). ``confirm`` is required only for a non-bridge
    (pre-existing) section (§5.1). ``dry_run`` previews."""

    material: str | None = Field(None, description="New material (must exist), if changing")
    depth: float | None = Field(None, description="New depth T3 (>0), if changing")
    width: float | None = Field(None, description="New width T2 (>0), if changing")
    color: int | None = Field(None, description="New color, if changing")
    notes: str | None = Field(None, description="New notes, if changing")
    dry_run: bool = Field(False, description="If true, preview without applying")
    confirm: bool = Field(False, description="Required to modify a non-bridge (pre-existing) section")


class RectangularSectionChange(BaseModel):
    """A section modification as facts: full before/after and a readable per-field diff."""

    previous: RectangularSection | None = Field(None, description="State before (real run)")
    current: RectangularSection | None = Field(None, description="State after / proposed")
    changes: list[str] = Field(..., description="Per-field diffs, e.g. ['depth: 0.045 → 0.050']")


class ModifyRectangularSectionResponse(BaseModel):
    """Result of modify_rectangular_section. Dry-run: ``would_apply`` (current=proposed);
    real run: ``applied`` (previous + current read back from SAP)."""

    dry_run: bool
    validation_passed: bool = True
    would_apply: RectangularSectionChange | None = None
    applied: RectangularSectionChange | None = None


# --- Write-side: section assignment to frames (batch, Fase 1g.7) -------------
# First BATCH write over pre-existing objects. The OAPI has no native heterogeneous
# batch (brechas §25), so the bridge composes a loop over SetSection. The external API
# is the same in both cases. Strict pre-validation means failed_at is reserved for an
# unexpected OAPI failure mid-loop (decisión #4, stop-on-first-failure).


class FrameAssignmentPreview(BaseModel):
    """One frame's current → proposed section (dry-run preview)."""

    frame: str
    current_section: str
    new_section: str


class FrameAssignmentApplied(BaseModel):
    """One frame's section change as applied (read back from SAP)."""

    frame: str
    previous_section: str
    current_section: str


class BatchFailure(BaseModel):
    """The frame at which a batch stopped, and why (only set if a mid-loop OAPI failure
    occurred — strict pre-validation makes this rare)."""

    frame: str
    reason: str


class AssignToFramesRequest(BaseModel):
    """Body for POST /v1/sections/{name}/assign-to-frames (homogeneous). Assigns one
    section to every frame in ``frame_names``. ``confirm`` mandatory (touches pre-existing
    frames, §5.1); ``dry_run`` previews."""

    frame_names: list[str] = Field(..., description="Frames to assign the section to")
    dry_run: bool = Field(False, description="If true, preview without applying")
    confirm: bool = Field(False, description="Mandatory: the operation touches pre-existing frames")


class FrameSectionAssignment(BaseModel):
    """One frame→section pair for a heterogeneous batch."""

    frame_name: str
    section_name: str


class AssignBatchRequest(BaseModel):
    """Body for POST /v1/sections/assign-batch (heterogeneous). Each item maps one frame
    to one section. ``confirm`` mandatory; ``dry_run`` previews."""

    assignments: list[FrameSectionAssignment] = Field(..., description="frame→section pairs")
    dry_run: bool = Field(False, description="If true, preview without applying")
    confirm: bool = Field(False, description="Mandatory: the operation touches pre-existing frames")


class AssignmentPreview(BaseModel):
    """Dry-run preview of a (homogeneous or heterogeneous) assignment batch."""

    frame_count: int
    current_assignments: list[FrameAssignmentPreview]
    changes: list[str] = Field(..., description="Per-frame diffs, e.g. ['4060: MGP10_33x73 → AI_45x95']")


class AssignmentResponse(BaseModel):
    """Result of an assignment batch (both homogeneous and heterogeneous use this).

    Dry-run: ``would_apply`` holds the preview, ``hint`` set if >10 frames. Real run:
    ``applied`` lists each frame changed (read back); ``failed_at`` is null in normal flow
    (strict pre-validation), set only on an unexpected mid-loop OAPI failure, with
    ``not_attempted`` the frames after it (decisión #4, stop-on-first-failure)."""

    dry_run: bool
    operation: str
    validation_passed: bool = True
    would_apply: AssignmentPreview | None = None
    applied: list[FrameAssignmentApplied] | None = None
    failed_at: BatchFailure | None = None
    not_attempted: list[str] | None = None
    hint: str | None = Field(None, description="Suggestion to use dry_run for large batches (>10)")


# --- Write-side: model state — lock + open_model (Fase 1g.8) ------------------
# State-level primitives (distinct from model_settings, which reads/sets configurable
# settings). They make the iterative write→analyze→write loop robust (§26 blockers).


class SetModelLockedRequest(BaseModel):
    """Body for POST /v1/model/locked. ``confirm`` mandatory (global state toggle, §5.3);
    ``dry_run`` previews. Idempotent — applying the current value is a valid no-op."""

    locked: bool = Field(..., description="Target lock state")
    dry_run: bool = Field(False, description="If true, preview without applying")
    confirm: bool = Field(False, description="Mandatory to apply (global state)")


class ModelLockChange(BaseModel):
    """The lock change as facts: state before/after. ``current_locked`` is read back."""

    previous_locked: bool | None = Field(None, description="Lock state before (real run)")
    current_locked: bool | None = Field(None, description="Current lock state (dry-run shows it)")
    new_locked: bool | None = Field(None, description="Target lock state (dry-run preview)")


class SetModelLockedResponse(BaseModel):
    dry_run: bool
    validation_passed: bool = True
    would_apply: ModelLockChange | None = None
    applied: ModelLockChange | None = None


class OpenModelRequest(BaseModel):
    """Body for POST /v1/model/open. ``path`` must be an absolute .sdb path that exists.
    ``confirm`` mandatory (replaces the loaded model, discarding unsaved changes);
    ``dry_run`` previews."""

    path: str = Field(..., description="Absolute path to the .sdb to open")
    dry_run: bool = Field(False, description="If true, preview without opening")
    confirm: bool = Field(False, description="Mandatory: replaces the loaded model")


class ModelOpenChange(BaseModel):
    """The model-open change as facts: paths before/after (read back from SAP)."""

    previous_model_path: str | None = Field(None, description="Path loaded before (real run)")
    current_model_path: str | None = Field(None, description="Path loaded after / current")
    new_model_path: str | None = Field(None, description="Path to open (dry-run preview)")


class OpenModelResponse(BaseModel):
    dry_run: bool
    validation_passed: bool = True
    would_apply: ModelOpenChange | None = None
    applied: ModelOpenChange | None = None
