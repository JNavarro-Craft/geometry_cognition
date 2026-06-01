from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.rhino_bridge_client.tools import extract_objects

logger = logging.getLogger(__name__)

mcp = FastMCP("rhino_bridge_client")


def _normalize_mcp_tool_arguments(
    *,
    input_path: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the extract_objects payload from MCP tool arguments.

    FastMCP exposes one JSON object per tool call. A single ``payload: dict``
    parameter forces clients to nest as ``{"payload": {"input_path": ...}}``;
    LLM clients typically send ``{"input_path": "..."}`` at the top level.
    Accept both shapes.
    """
    logger.info(
        "rhino_bridge_client MCP: received input_path=%r payload_keys=%s",
        input_path,
        sorted(payload.keys()) if isinstance(payload, dict) else None,
    )
    chosen: str | None = None
    if input_path is not None and str(input_path).strip():
        chosen = str(input_path).strip()
    elif isinstance(payload, dict):
        nested = payload.get("input_path")
        if nested is not None and str(nested).strip():
            chosen = str(nested).strip()
    out: dict[str, Any] = {"input_path": chosen} if chosen else {}
    logger.info("rhino_bridge_client MCP: normalized input_path for extract_objects=%r", chosen)
    return out


@mcp.tool(name="extract_objects")
def extract_objects_tool(
    input_path: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract normalized objects from a Rhino ``.3dm`` file or JSON fixture. Prefer ``input_path``."""
    mcp_payload = _normalize_mcp_tool_arguments(input_path=input_path, payload=payload)
    return extract_objects(mcp_payload)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
