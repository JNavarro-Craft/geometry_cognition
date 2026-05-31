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
    assert_change,
    delete_snapshot,
    describe_model,
    diff_object,
    diff_snapshots,
    inspect_object,
    list_snapshots,
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
    Call this BEFORE building filters so you never guess a key that does not exist."""
    return describe_model()


@mcp.tool(name="query_objects")
def query_objects_tool(
    filters: dict[str, Any] | None = None,
    source: str = "live",
    limit: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Query objects by AND-combined filters over the live model (source="live")
    or a persisted snapshot (source=<label>). Filters: layers, types,
    name_contains, user_text_key, user_text (key=value), is_block_instance."""
    return query_objects(filters=filters, source=source, limit=limit, fields=fields)


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
    """Fetch the live detail of a single object via /v1/live/objects/{guid}."""
    return inspect_object(guid=guid, detail_level=detail_level, user_text=user_text)


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
