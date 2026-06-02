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
    get_analysis_status,
    get_combinations,
    get_distributed_loads_on_frame,
    get_frames,
    get_joints,
    get_load_case_details,
    get_load_cases,
    get_load_patterns,
    get_materials,
    get_point_loads_on_joint,
    get_section_properties,
    get_sections,
    run_analysis,
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


if __name__ == "__main__":
    mcp.run()
