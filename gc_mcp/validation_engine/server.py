from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.validation_engine.tools import validate_hypotheses
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("validation_engine")


@mcp.tool(name="validate_hypotheses")
def validate_hypotheses_tool(
    hypotheses: list[Any] | None = None,
    evidence_items: list[Any] | None = None,
    entities: list[Any] | None = None,
    relations: list[Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict:
    """
    Accept both MCP shapes:
    - flat: {hypotheses, evidence_items, entities, relations}
    - nested: {payload: {...}}
    """
    merged: dict[str, Any] = {}
    if isinstance(payload, dict):
        merged.update(payload)
    if hypotheses is not None:
        merged["hypotheses"] = hypotheses
    if evidence_items is not None:
        merged["evidence_items"] = evidence_items
    if entities is not None:
        merged["entities"] = entities
    if relations is not None:
        merged["relations"] = relations

    logger.info(
        "validation_engine MCP: merged keys=%s hyp=%s ev=%s ent=%s rel=%s",
        sorted(merged.keys()),
        len(merged.get("hypotheses") or []),
        len(merged.get("evidence_items") or []),
        len(merged.get("entities") or []),
        len(merged.get("relations") or []),
    )
    return validate_hypotheses(merged)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
