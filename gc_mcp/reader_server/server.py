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
    get_analysis_summary,
    get_confirmed_relations,
    get_evidence_for_relation,
    get_object_details,
    get_objects,
    get_reasoning_output,
    get_relations_for_object,
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


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()

