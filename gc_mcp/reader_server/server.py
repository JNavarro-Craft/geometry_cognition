from __future__ import annotations

from pathlib import Path
import sys

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # fallback for environments already using fastmcp package
    from fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.reader_server.tools import (
    find_orphans,
    get_analysis_summary,
    get_confirmed_relations,
    get_evidence_for_relation,
    get_groups,
    get_inventory_summary,
    get_layers,
    get_object_details,
    get_objects,
    get_objects_by_group,
    get_objects_by_layer,
    get_objects_by_user_text,
    get_reasoning_output,
    get_relations_for_object,
    get_user_text_keys_summary,
)

mcp = FastMCP("reader_server")


@mcp.tool(name="get_analysis_summary")
def get_analysis_summary_tool() -> dict:
    return get_analysis_summary()


@mcp.tool(name="get_objects")
def get_objects_tool(limit: int | None = None) -> dict:
    return get_objects(limit=limit)


@mcp.tool(name="get_object_details")
def get_object_details_tool(object_id: str) -> dict:
    return get_object_details(object_id=object_id)


@mcp.tool(name="get_confirmed_relations")
def get_confirmed_relations_tool(predicate: str | None = None) -> dict:
    return get_confirmed_relations(predicate=predicate)


@mcp.tool(name="get_relations_for_object")
def get_relations_for_object_tool(object_id: str, assertion_level: str | None = None) -> dict:
    return get_relations_for_object(object_id=object_id, assertion_level=assertion_level)


@mcp.tool(name="get_evidence_for_relation")
def get_evidence_for_relation_tool(relation_id: str) -> dict:
    return get_evidence_for_relation(relation_id=relation_id)


@mcp.tool(name="get_reasoning_output")
def get_reasoning_output_tool() -> dict:
    return get_reasoning_output()


@mcp.tool(name="get_inventory_summary")
def get_inventory_summary_tool() -> dict:
    return get_inventory_summary()


@mcp.tool(name="get_layers")
def get_layers_tool() -> dict:
    return get_layers()


@mcp.tool(name="get_groups")
def get_groups_tool() -> dict:
    return get_groups()


@mcp.tool(name="get_objects_by_layer")
def get_objects_by_layer_tool(layer_name: str, limit: int | None = None) -> dict:
    return get_objects_by_layer(layer_name=layer_name, limit=limit)


@mcp.tool(name="get_objects_by_group")
def get_objects_by_group_tool(group_name: str, limit: int | None = None) -> dict:
    return get_objects_by_group(group_name=group_name, limit=limit)


@mcp.tool(name="get_objects_by_user_text")
def get_objects_by_user_text_tool(key: str, value: str | None = None, limit: int | None = None) -> dict:
    return get_objects_by_user_text(key=key, value=value, limit=limit)


@mcp.tool(name="find_orphans")
def find_orphans_tool(criterion: str = "no_group", limit: int | None = None) -> dict:
    return find_orphans(criterion=criterion, limit=limit)


@mcp.tool(name="get_user_text_keys_summary")
def get_user_text_keys_summary_tool() -> dict:
    return get_user_text_keys_summary()


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()

