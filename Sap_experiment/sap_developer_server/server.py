"""MCP entrypoint for sap_developer_server. Registers the read-only SAP tools.

Run as an MCP server (stdio) and register in Claude Desktop. It is a thin consumer
of the SAP bridge over HTTP; all SAP access happens in the bridge process.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fallback for environments using the fastmcp package
    from fastmcp import FastMCP

# Allow `from Sap_experiment.sap_developer_server...` style imports when launched directly.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Sap_experiment.sap_developer_server.tools import (
    get_frames,
    get_joints,
    get_materials,
    get_section_properties,
    get_sections,
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


if __name__ == "__main__":
    mcp.run()
