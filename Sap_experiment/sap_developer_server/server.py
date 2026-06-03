"""MCP entrypoint for sap_developer_server. Registers the SAP tools.

Run as an MCP server (stdio) and register in Claude Desktop. It is a thin consumer
of the SAP bridge over HTTP; all SAP access happens in the bridge process. All tools
are read-only except run_analysis, which mutates computation state (it produces results
and may lock the model) but never modifies the model definition.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fallback for environments using the fastmcp package
    from fastmcp import FastMCP

# Allow `from Sap_experiment.sap_developer_server...` style imports when launched directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Sap_experiment.sap_developer_server.tools import (
    assign_section_to_frames,
    assign_sections_to_frames,
    create_material,
    create_rectangular_section,
    create_savepoint,
    get_analysis_status,
    get_combinations,
    get_distributed_loads_on_frame,
    get_frame_forces,
    get_frames,
    get_joint_displacements,
    get_joint_reactions,
    get_joints,
    get_load_case_details,
    get_load_cases,
    get_load_patterns,
    get_materials,
    get_model_settings,
    get_point_loads_on_joint,
    get_section_properties,
    get_sections,
    list_savepoints,
    modify_rectangular_section,
    new_blank_model,
    open_model,
    reset_workspace,
    restore_savepoint,
    run_analysis,
    set_active_dof,
    set_material_properties_isotropic,
    set_model_locked,
    set_present_units,
)

mcp = FastMCP("sap_developer_server")


@mcp.tool(name="get_joints")
def get_joints_tool() -> dict[str, Any]:
    """Every point object in the open SAP model: name, global Cartesian coordinates
    (in the model's present units, echoed under ``units``) and the raw 6-DOF
    restraint flags [U1,U2,U3,R1,R2,R3] (True = restrained). Facts only — no
    pinned/fixed/roller classification (that is your domain reasoning)."""
    return get_joints()


@mcp.tool(name="get_frames")
def get_frames_tool() -> dict[str, Any]:
    """Every frame (line) object: name, the two end point names (point_i/point_j,
    matching get_joints names — join on them for coordinates) and the assigned
    section property. Facts only — no chord/strut/diagonal classification."""
    return get_frames()


@mcp.tool(name="get_sections")
def get_sections_tool() -> dict[str, Any]:
    """The frame section property catalogue defined in the model: each section's name
    and SAP prop_type. Names are model-supplied labels relayed verbatim — no
    interpretation, no dimensions. Cross-reference get_frames for which are used."""
    return get_sections()


@mcp.tool(name="get_materials")
def get_materials_tool() -> dict[str, Any]:
    """The material catalogue defined in the model: each material's name, raw SAP
    mat_type (Steel/Concrete/NoDesign/…) and basic mechanical facts (e, nu,
    thermal_coeff, shear_modulus, weight/mass per volume) when available, in present
    units. No interpretation — 'MGP10' is reported as its SAP type, not 'timber'. Fields
    are null when SAP does not provide them, never faked."""
    return get_materials()


@mcp.tool(name="get_section_properties")
def get_section_properties_tool(name: str) -> dict[str, Any]:
    """Dimensions + universal properties for ONE frame section by exact name (from
    get_sections): prop_type, referenced material, dimensions (shape-specific geometry
    keyed by SAP parameter names, e.g. depth/width) and properties (area, inertias,
    torsion, moduli, radii of gyration), all in present units. Facts only — no
    cross-shape normalization. Unsupported shapes return a structured error."""
    return get_section_properties(name)


@mcp.tool(name="get_load_patterns")
def get_load_patterns_tool() -> dict[str, Any]:
    """The load pattern catalogue: each pattern's name, raw load_type (Dead/Live/Wind/
    Snow/…) and self_weight_multiplier. Names relayed verbatim ('PESO PROPIO' not
    translated); the MCP never assumes which patterns a model should have."""
    return get_load_patterns()


@mcp.tool(name="get_load_cases")
def get_load_cases_tool() -> dict[str, Any]:
    """The analysis load case catalogue: each case's name and raw case_type
    (LinearStatic/Modal/…). Facts only — a case's internal definition is a later
    primitive."""
    return get_load_cases()


@mcp.tool(name="get_combinations")
def get_combinations_tool() -> dict[str, Any]:
    """The load combination catalogue: each combo's name, combo_type ('Linear Additive'/
    'Envelope'/…) with raw combo_type_code, and items (consolidated: case_name,
    case_type 'LoadCase'|'LoadCombo', scale_factor). Parallel arrays recomposed for you.
    No interpretation — 'ENVOLVENTE' is just combo_type 'Envelope'. LoadCase items
    reference get_load_cases names; LoadCombo items reference other combos."""
    return get_combinations()


@mcp.tool(name="get_distributed_loads_on_frame")
def get_distributed_loads_on_frame_tool(frame_name: str) -> dict[str, Any]:
    """Distributed loads on ONE frame (exact name from get_frames), across all patterns.
    Each item: load_pattern, load_type ('Force'/'Displacement'), direction (e.g.
    'Gravity', 'Local 2') + raw direction_code, coord_system, rel_dist_start/end (0..1),
    value_start/end (present units). Empty loads = none on that frame (not an error).
    Directions relayed raw; load_pattern references get_load_patterns names."""
    return get_distributed_loads_on_frame(frame_name)


@mcp.tool(name="get_point_loads_on_joint")
def get_point_loads_on_joint_tool(joint_name: str) -> dict[str, Any]:
    """Point loads (force + moment) on ONE joint (exact name from get_joints), across all
    patterns. Each item: load_pattern, coord_system, f1/f2/f3 (force), m1/m2/m3 (moment),
    present units. Empty loads = none on that joint (not an error). load_pattern
    references get_load_patterns names."""
    return get_point_loads_on_joint(joint_name)


@mcp.tool(name="get_load_case_details")
def get_load_case_details_tool(case_name: str) -> dict[str, Any]:
    """Composition of ONE load case (exact name from get_load_cases): case_type and
    loads. LinearStatic → applied patterns with load_type, load_pattern, scale_factor
    (mirrors get_combinations items). Other types → unsupported_case_type=true, loads=[]
    (type reported, internals deferred; not an error). load_pattern references
    get_load_patterns names."""
    return get_load_case_details(case_name)


@mcp.tool(name="run_analysis")
def run_analysis_tool(cases_to_run: Optional[list[str]] = None) -> dict[str, Any]:
    """Run the structural analysis on the open SAP model. MUTATES computation state
    (produces results, may lock the model); does NOT modify the model definition.
    cases_to_run=None runs all pending cases; a list runs only those (names from
    get_load_cases, validated first; run flags restored after). Returns ran_count,
    cases_run, runtime_seconds (BLOCKING — may take a while), model_is_locked and a
    per-case status snapshot. Model-side failures (non-convergence) are reported as
    facts, never judged. Re-running is idempotent."""
    return run_analysis(cases_to_run)


@mcp.tool(name="get_analysis_status")
def get_analysis_status_tool() -> dict[str, Any]:
    """Read current analysis status (read-only): model_is_locked plus, per load case,
    case_name, status ('Not Run'/'Could Not Start'/'Not Finished'/'Finished') with raw
    status_code, and has_run (True only when Finished). Facts only — a locked model or an
    unfinished case is reported as-is, never judged."""
    return get_analysis_status()


@mcp.tool(name="get_joint_displacements")
def get_joint_displacements_tool(joint_name: str, case_name: str) -> dict[str, Any]:
    """6-DOF displacement of ONE joint in ONE LinearStatic case (global, present units):
    u1/u2/u3 (translations), r1/r2/r3 (rotations). Read-only post-analysis. Restrained
    DOFs read ~0. case_not_run if the case has no results (call run_analysis first);
    unsupported_case_type if not LinearStatic. A large displacement is a fact, not failure."""
    return get_joint_displacements(joint_name, case_name)


@mcp.tool(name="get_joint_reactions")
def get_joint_reactions_tool(joint_name: str, case_name: str) -> dict[str, Any]:
    """6-DOF reaction (force + moment) of ONE joint in ONE LinearStatic case (global,
    present units): f1/f2/f3, m1/m2/m3. Read-only post-analysis. Unrestrained DOFs read
    ~0; a free joint reads zeros (not an error). case_not_run / unsupported_case_type as
    for displacements. Reactions balance applied loads (equilibrium) — a client cross-check."""
    return get_joint_reactions(joint_name, case_name)


@mcp.tool(name="get_frame_forces")
def get_frame_forces_tool(frame_name: str, case_name: str, station: Optional[float] = None) -> dict[str, Any]:
    """Internal forces along ONE frame in ONE LinearStatic case: stations with
    relative_distance (0..1), absolute_distance, p (axial), v2/v3 (shears), t (torsion),
    m2/m3 (moments), present units. Read-only post-analysis. station (0..1) returns just
    that one; omit for all. case_not_run / unsupported_case_type as above. A large moment
    is a number, not 'overstress'."""
    return get_frame_forces(frame_name, case_name, station)


@mcp.tool(name="get_model_settings")
def get_model_settings_tool() -> dict[str, Any]:
    """The model's configuration: active_dof (6 flags [U1,U2,U3,R1,R2,R3], True=active,
    same convention as joint restraints), model_is_locked, present_units + database_units
    (present = active view, database = internal storage). Facts only — the MCP never
    labels the DOF pattern 'Plane Frame'/'2D'; you recognise it from the flags."""
    return get_model_settings()


@mcp.tool(name="create_savepoint")
def create_savepoint_tool(name: str, dry_run: bool = False) -> dict[str, Any]:
    """WRITE (filesystem): save the current model state to a savepoint file
    <model>__sp_<name>.sdb. Refuses if that name exists (no silent overwrite). dry_run=true
    previews target path + size + writability without writing. Undo infrastructure: take a
    savepoint before a risky write, restore it if unwanted. Does NOT change the model in
    memory."""
    return create_savepoint(name, dry_run)


@mcp.tool(name="restore_savepoint")
def restore_savepoint_tool(name: str, confirm: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """WRITE (destructive): restore a savepoint, REPLACING the loaded model with it and
    discarding unsaved changes. confirm=true is mandatory (else confirm_required);
    dry_run=true previews without replacing; missing savepoint → savepoint_not_found. Do
    NOT pass confirm automatically — preview with dry_run, decide, then confirm."""
    return restore_savepoint(name, confirm, dry_run)


@mcp.tool(name="list_savepoints")
def list_savepoints_tool() -> dict[str, Any]:
    """Read-only: list the savepoints for the current model (name, path, created_at,
    size_bytes). Empty list if none (not an error). A filesystem scan, works even when SAP
    is busy."""
    return list_savepoints()


@mcp.tool(name="set_active_dof")
def set_active_dof_tool(active_dof: list[bool], dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE (mutates the model; global setting): set the active DOFs. active_dof must be
    exactly 6 booleans [U1,U2,U3,R1,R2,R3]. confirm=true is mandatory (else
    confirm_required); dry_run=true previews with a per-DOF diff without applying. Facts
    only — validates shape, relays SAP, does NOT judge the pattern (SAP accepts all-false)
    or auto-unlock a locked model. Recommended: create_savepoint → dry_run → review →
    confirm → verify → restore_savepoint if unwanted."""
    return set_active_dof(active_dof, dry_run, confirm)


@mcp.tool(name="set_present_units")
def set_present_units_tool(units: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE (mutates the model; global setting): set the present (display) units by NAME,
    e.g. 'N_m_C', 'kgf_m_C', 'lb_ft_F'. Unknown name → unknown_unit_system (supported names
    listed). confirm=true mandatory (else confirm_required); dry_run=true previews with a
    change_summary 'kgf_m_C → N_m_C'. A display preference — the read-side then reports in
    the new units (distances stay metres; forces/moments rescale, kgf→N ≈ ×9.81); the bridge
    converts nothing itself. database_units untouched. Recommended: create_savepoint →
    dry_run → review → confirm → verify → restore_savepoint if unwanted."""
    return set_present_units(units, dry_run, confirm)


@mcp.tool(name="create_material")
def create_material_tool(name: str, material_type: str, dry_run: bool = False) -> dict[str, Any]:
    """WRITE (new object): create a material. name MUST start with the bridge prefix (default
    'AI_') else prefix_required. material_type is an eMatType name: Steel, Concrete, NoDesign,
    Aluminum, ColdFormed, Rebar, Tendon, Masonry — NO 'Wood' in SAP (use 'NoDesign' for
    timber); unknown → unknown_material_type. Existing name → name_already_exists (SAP would
    overwrite silently). No confirm. dry_run previews. New material has only defaults — call
    set_material_properties_isotropic next."""
    return create_material(name, material_type, dry_run)


@mcp.tool(name="set_material_properties_isotropic")
def set_material_properties_isotropic_tool(
    name: str, E: float, poisson_ratio: float, thermal_coef: float,
    dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """WRITE: set a material's isotropic properties (E, poisson_ratio, thermal_coef). Material
    must exist (else object_not_found). confirm=true required only for a NON-bridge
    (pre-existing) material like 'MGP10' (§5.1); a bridge-owned 'AI_' material needs none.
    dry_run previews with a per-field diff. Values are in the model's PRESENT UNITS — know
    what those are (get_model_settings); the bridge converts nothing. SAP derives G from E and
    poisson_ratio."""
    return set_material_properties_isotropic(name, E, poisson_ratio, thermal_coef, dry_run, confirm)


@mcp.tool(name="create_rectangular_section")
def create_rectangular_section_tool(
    name: str, material: str, depth: float, width: float,
    color: Optional[int] = None, notes: str = "", dry_run: bool = False
) -> dict[str, Any]:
    """WRITE (new object): create a rectangular frame section. name MUST start with the bridge
    prefix (default 'AI_') else prefix_required. material must exist (object_not_found). depth
    (T3) and width (T2) > 0 (invalid_dimensions), in present length units. Existing name →
    name_already_exists (SAP would overwrite silently). No confirm. dry_run previews. Applied
    values read back from SAP."""
    return create_rectangular_section(name, material, depth, width, color, notes, dry_run)


@mcp.tool(name="modify_rectangular_section")
def modify_rectangular_section_tool(
    name: str, material: Optional[str] = None, depth: Optional[float] = None,
    width: Optional[float] = None, color: Optional[int] = None, notes: Optional[str] = None,
    dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """WRITE: modify an existing rectangular section. Must exist and be Rectangular
    (object_not_found / section_type_mismatch). Pass only fields to change — none →
    nothing_to_modify. confirm=true required only for a NON-bridge (pre-existing) section like
    'MGP10_33x73' (§5.1); a bridge-owned 'AI_' section needs none. dry_run previews with a
    per-field diff. Dimensions in present units."""
    return modify_rectangular_section(name, material, depth, width, color, notes, dry_run, confirm)


@mcp.tool(name="assign_section_to_frames")
def assign_section_to_frames_tool(
    section_name: str, frame_names: list[str], dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """WRITE (batch): assign ONE section to many frames. The section and EVERY frame must
    exist (strict pre-validation → object_not_found listing the missing). Empty list →
    empty_batch. confirm=true mandatory (touches pre-existing frames). dry_run previews
    per-frame changes. Returns applied (previous→current, read back), failed_at (null in
    normal flow), not_attempted; a >10-frame result adds a hint. Use create_savepoint first."""
    return assign_section_to_frames(section_name, frame_names, dry_run, confirm)


@mcp.tool(name="assign_sections_to_frames")
def assign_sections_to_frames_tool(
    assignments: list[dict], dry_run: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """WRITE (batch): assign sections to frames per a heterogeneous mapping. assignments is a
    list of {"frame_name": ..., "section_name": ...}. Every referenced section and frame must
    exist. Empty → empty_batch. confirm=true mandatory; dry_run previews. Same applied/
    failed_at/not_attempted shape as assign_section_to_frames. The bridge loops internally
    (no native heterogeneous batch in the OAPI)."""
    return assign_sections_to_frames(assignments, dry_run, confirm)


@mcp.tool(name="set_model_locked")
def set_model_locked_tool(locked: bool, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE (global state): set the model lock. run_analysis LOCKS the model and SAP then
    rejects model edits (create/assign/modify) → oapi_call_failed. Call set_model_locked(false,
    confirm=true) to UNLOCK and keep modifying — this closes an iterative write→analyze→write
    loop. confirm=true mandatory; dry_run previews; idempotent. The bridge does NOT auto-unlock."""
    return set_model_locked(locked, dry_run, confirm)


@mcp.tool(name="open_model")
def open_model_tool(path: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE: open a model, REPLACING the loaded one. path must be an ABSOLUTE .sdb that exists
    (else invalid_path / file_not_found — checked before opening). confirm=true mandatory
    (discards unsaved changes); dry_run previews. The opened model becomes the new base and the
    bridge re-anchors to a fresh workspace derived from it."""
    return open_model(path, dry_run, confirm)


@mcp.tool(name="new_blank_model")
def new_blank_model_tool(units: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE: initialize an EMPTY model from scratch (build-from-blank). units is a unit-system
    name (eUnits member, e.g. 'kgf_m_C'; else unknown_unit_system). DESTRUCTIVE: discards the
    loaded model WITHOUT saving → confirm=true mandatory (else confirm_required); dry_run previews.
    The empty model (0 joints, 0 frames) gets a temp workspace and no base file; build it with the
    create_* primitives, then save_workspace_as(path) to materialize it as a new base."""
    return new_blank_model(units, dry_run, confirm)


@mcp.tool(name="reset_workspace")
def reset_workspace_tool(dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    """WRITE: reset the bridge's transient workspace to a clean copy of the immutable BASE
    model. The bridge works on a workspace copy so the user's base file is never written; this
    regenerates that copy from the clean base, returning you to a known baseline without using
    savepoints. confirm=true mandatory (discards workspace changes); dry_run previews. Use
    between iterations of a what-if experiment to start each from the same clean baseline."""
    return reset_workspace(dry_run, confirm)


if __name__ == "__main__":
    mcp.run()
