from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fallback for environments already using fastmcp package
    from fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.developer_server.tools import (
    aggregate,
    assert_change,
    bill_of_materials,
    compute_contacts,
    delete_snapshot,
    describe_model,
    diff_object,
    diff_snapshots,
    expand_block,
    get_edges,
    get_faces,
    get_vertices,
    inspect_object,
    list_block_definitions,
    list_snapshots,
    project_to_plane,
    prune_snapshots_tool_logic,
    query_objects,
    take_snapshot,
)

mcp = FastMCP("developer_server")


@mcp.tool(name="take_snapshot")
def take_snapshot_tool(
    label: str,
    sample_limit: int = 20,
    layers: list[str] | None = None,
    types: list[str] | None = None,
    name: str | None = None,
    user_text_key: str | None = None,
    bbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture the current Rhino model state (via the bridge) under the given label.
    Overwrites any previous snapshot with the same label.

    Optional filters reduce the captured scope (AND-combined). They are passed
    to the bridge's live query; the unfiltered case (all None/empty) behaves
    exactly like before. ``user_text_key`` filters by presence of an arbitrary
    user_text key (the MCP does not know any concrete domain keys).

    The returned ``status`` and ``filter_report`` tell you honestly what the
    filter did: ``ok`` (applied or no filter), ``filter_valid_empty`` (applied,
    matched 0 — trustworthy), or ``filter_not_applied`` (live strategy failed and
    the fallback returned the FULL model unfiltered — do not trust matched_count).
    """
    return take_snapshot(
        label=label,
        sample_limit=sample_limit,
        layers=layers,
        types=types,
        name=name,
        user_text_key=user_text_key,
        bbox=bbox,
    )


@mcp.tool(name="list_snapshots")
def list_snapshots_tool() -> dict[str, Any]:
    """List persisted snapshots in ``${GC_OUTPUTS_DIR}/dev_snapshots/``."""
    return list_snapshots()


@mcp.tool(name="describe_model")
def describe_model_tool() -> dict[str, Any]:
    """Discovery catalogue of the live model: real layers, Rhino types, groups,
    user_text keys (with counts + example values) and block definitions.

    START HERE before any filtered query or snapshot. It returns the exact
    layer names, type names and user_text keys that exist in THIS model, so you
    pass real values to query_objects/take_snapshot instead of guessing names
    that the bridge would silently ignore (matching everything)."""
    return describe_model()


@mcp.tool(name="query_objects")
def query_objects_tool(
    filters: dict[str, Any] | None = None,
    source: str = "live",
    limit: int | None = None,
    fields: list[str] | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    """Query objects by AND-combined filters over the live model (source="live")
    or a persisted snapshot (source=<label>, queries a past state).

    VALID filter keys (exact names — anything else is ignored, NOT an error):
      - layers: list[str]        exact full-path layer names ("Parent::Child")
      - types: list[str]         exact Rhino type names ("Brep", "Mesh", ...)
      - name_contains: str       case-insensitive substring of the object name
      - user_text_key: str       object has this user_text key
      - user_text: {key: value}  object's user_text matches these pairs exactly
      - is_block_instance: bool  filter block instances

    Common mistakes that silently match EVERYTHING: "layer"/"type" (singular),
    "where", "name". If matched_count looks like the whole scene, your filter
    key is probably wrong.

    ALWAYS call describe_model() first to see the real layers, types and
    user_text keys in THIS model — never guess a filter value.

    Example: {"layers": ["Walls::Exterior"], "user_text": {"Material": "Steel"}}

    Pagination: offset skips the first N matches, limit caps the page. When more
    remain, the result carries next_offset + has_more — page through large match
    sets instead of pulling everything (and overflowing) in one call.
    """
    return query_objects(filters=filters, source=source, limit=limit, fields=fields, offset=offset)


@mcp.tool(name="aggregate")
def aggregate_tool(
    group_by: list[str] | None = None,
    metrics: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    source: str = "live",
) -> dict[str, Any]:
    """Group objects and compute metrics (counts/takeoffs), over the live model or a
    snapshot. group_by: field names incl. "user_text.<key>" and geometry scalars
    (volume, area, length, face_count, edge_count). metrics: ["count","sum:volume",
    "avg:length","min:<f>","max:<f>"]. filters: same as query_objects. Agnostic: the
    MCP groups/sums whatever you name; domain meaning is the caller's."""
    return aggregate(group_by=group_by, metrics=metrics, filters=filters, source=source)


@mcp.tool(name="compute_contacts")
def compute_contacts_tool(
    object_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    tolerance: float = 1e-3,
) -> dict[str, Any]:
    """Detect REAL contacts between solids and report WHERE each contact is — the
    topological-reasoning primitive. Returns not just which pairs touch but the
    location (point / curve / surface patch), so a caller can deduce joints,
    extremities or where a connector sits (this tool computes none of those).

    Pass ``object_ids`` (explicit GUIDs) or ``filters`` (same keys as query_objects;
    matching objects are used as the set). ``tolerance`` = max gap treated as touching.
    Each contact: {pair, contact_type (point|curve|surface), contact_point |
    contact_curve | contact_region_bbox, approx_area}. Non-solid objects -> skipped.

    Agnostic (see docs/agnostic_principle.md): touching is meaningful in any domain,
    needs no knowledge of what the object is, and the client cannot derive it without a
    geometry engine — so the primitive is exposed; the reasoning ON it stays in the client."""
    return compute_contacts(object_ids=object_ids, filters=filters, tolerance=tolerance)


@mcp.tool(name="bill_of_materials")
def bill_of_materials_tool(only_with_instances: bool = True) -> dict[str, Any]:
    """Per block definition: instance_count x content breakdown (member type counts,
    annotation texts, total curve length/area). Shortcut over list_block_definitions +
    expand_block. The caller multiplies by instance_count and applies domain meaning."""
    return bill_of_materials(only_with_instances=only_with_instances)


@mcp.tool(name="delete_snapshot")
def delete_snapshot_tool(label: str) -> dict[str, Any]:
    """Delete all persisted snapshots for the given label. Returns status ``not_found`` if none exist."""
    return delete_snapshot(label=label)


@mcp.tool(name="prune_snapshots")
def prune_snapshots_tool(keep_latest_n: int = 1) -> dict[str, Any]:
    """Keep only the ``keep_latest_n`` most recent snapshots per label; delete older same-label captures."""
    return prune_snapshots_tool_logic(keep_latest_n=keep_latest_n)


@mcp.tool(name="diff_snapshots")
def diff_snapshots_tool(
    label_a: str,
    label_b: str,
    bbox_tolerance: float = 1e-6,
    geom_rel_tolerance: float = 1e-9,
    geom_abs_tolerance: float = 1e-6,
    detail: str = "full",
) -> dict[str, Any]:
    """Diff two snapshots by GUID. Returns created / deleted / modified rows.

    Geometric scalars (volume, area, face_count, edge_count, is_closed) are
    compared when both snapshots are developer_snapshot.v2; otherwise a
    geometry_diff.warning is emitted and the geometric comparison is skipped.
    ``geom_rel_tolerance`` and ``geom_abs_tolerance`` apply to volume and area
    (counts and bool use strict equality).

    ``detail``:
      - ``"full"`` (default): each modified row carries the full ``changes``
        dict. Output matches the previous behaviour exactly.
      - ``"summary"``: each modified row carries only ``changed_categories``
        (sorted list of category keys, no values). Designed to fit large diffs
        in context; use ``diff_object`` to drill into a specific GUID.
    """
    return diff_snapshots(
        label_a=label_a,
        label_b=label_b,
        bbox_tolerance=bbox_tolerance,
        geom_rel_tolerance=geom_rel_tolerance,
        geom_abs_tolerance=geom_abs_tolerance,
        detail=detail,
    )


@mcp.tool(name="diff_object")
def diff_object_tool(
    label_a: str,
    label_b: str,
    guid: str,
    bbox_tolerance: float = 1e-6,
    geom_rel_tolerance: float = 1e-9,
    geom_abs_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Return the full diff detail for a single GUID across two snapshots.

    Status values: ``modified`` (with ``changes`` identical to what
    ``diff_snapshots(detail='full')`` would emit), ``unchanged``, ``created``
    (only in B, with ``full_object_b``), ``deleted`` (only in A, with
    ``full_object_a``), ``object_not_in_snapshots``.
    """
    return diff_object(
        label_a=label_a,
        label_b=label_b,
        guid=guid,
        bbox_tolerance=bbox_tolerance,
        geom_rel_tolerance=geom_rel_tolerance,
        geom_abs_tolerance=geom_abs_tolerance,
    )


@mcp.tool(name="inspect_object")
def inspect_object_tool(
    guid: str, detail_level: str = "full", user_text: str = "values"
) -> dict[str, Any]:
    """Fetch the live detail of a single object via /v1/live/objects/{guid}.
    With detail_level="full", annotation objects (text, dimensions, leaders) include
    an ``annotation_text`` field with their resolved plain_text."""
    return inspect_object(guid=guid, detail_level=detail_level, user_text=user_text)


@mcp.tool(name="project_to_plane")
def project_to_plane_tool(
    plane: dict[str, Any],
    object_ids: list[str] | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project solids onto a plane; return 2D polygons in the plane's local (u,v). One
    polygon per face. Pass ``plane={"origin":[x,y,z],"normal":[x,y,z]}`` plus
    ``object_ids`` or ``filters`` (query_objects keys). Each: {object_id, polygons_2d,
    warnings}. A face perpendicular to the plane -> degenerate polygon + warning, not an
    error. The raw 3D->2D primitive: the client composes drawing / aperture detection /
    coverage; the MCP names none. Agnostic per docs/agnostic_principle.md."""
    return project_to_plane(plane=plane, object_ids=object_ids, filters=filters)


@mcp.tool(name="get_vertices")
def get_vertices_tool(guid: str) -> dict[str, Any]:
    """Vertex coordinates of one solid: list of {index, coord:[x,y,z]}. Works for
    Brep/Extrusion/Mesh; unsupported type -> honest error. Raw geometry the aggregate
    fields cannot give. Agnostic (docs/agnostic_principle.md): universal, no domain
    knowledge, not client/LLM-derivable from aggregates -> expose the primitive."""
    return get_vertices(guid=guid)


@mcp.tool(name="get_edges")
def get_edges_tool(guid: str) -> dict[str, Any]:
    """Edges of one solid: {index, start, end, length, is_curved, samples}. ``samples``
    only when curved. ``index`` is referenced by get_faces.edge_indices. Brep/Extrusion/
    Mesh; unsupported -> honest error. Agnostic per docs/agnostic_principle.md."""
    return get_edges(guid=guid)


@mcp.tool(name="get_faces")
def get_faces_tool(guid: str) -> dict[str, Any]:
    """Faces of one solid: {index, normal, area, centroid, perimeter, is_planar,
    edge_indices}. ``edge_indices`` ties each face to its bounding edges (topology),
    so a face is part of a solid, not a floating normal. Brep/Extrusion/Mesh;
    unsupported -> honest error. Agnostic per docs/agnostic_principle.md."""
    return get_faces(guid=guid)


@mcp.tool(name="list_block_definitions")
def list_block_definitions_tool(
    summary: bool = False, limit: int | None = None, offset: int | None = None
) -> dict[str, Any]:
    """List block definitions in the live model (definition_name, member object_count,
    instance_count, bbox). Use expand_block(name) to read what is inside a definition.
    summary=True slims each row to name + counts (drops bbox and definition_id).
    limit/offset page the list (next_offset + has_more when more remain) — for models
    with hundreds of definitions, pass summary=True together with a limit."""
    return list_block_definitions(summary=summary, limit=limit, offset=offset)


@mcp.tool(name="expand_block")
def expand_block_tool(
    definition_name: str, resolve_instances: bool = False, summary: bool = False
) -> dict[str, Any]:
    """Read the objects composing a block definition (raw content, no transform applied):
    child geometry, their user_text, materials and annotation text — data invisible from
    the instance alone. definition_name is case-sensitive (see list_block_definitions).
    With resolve_instances=True, also returns an ``instances`` block placing each member's
    bbox at every instance's location (lightweight; geometry not moved).
    With summary=True, drops per-member geometry and returns a content_summary (member
    type counts, annotation texts, total member length/area) — for definitions with
    hundreds of members that would otherwise overflow the response."""
    return expand_block(
        definition_name=definition_name, resolve_instances=resolve_instances, summary=summary
    )


@mcp.tool(name="assert_change")
def assert_change_tool(
    label_a: str, label_b: str, expectations: dict[str, Any]
) -> dict[str, Any]:
    """Validate expectations (created/deleted/modified counts and filters) against a diff."""
    return assert_change(label_a=label_a, label_b=label_b, expectations=expectations)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
